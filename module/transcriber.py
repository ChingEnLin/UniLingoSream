import asyncio
import logging
import json
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class TranscriberTranslator:
    """ Transcriber module for transcribing and translating audio data using Gemini Live Client """
    # Gemini 3.5 Live pricing per token: $3.50/1M input, $21.00/1M output
    PROMPT_TOKEN_COST = 0.0000035
    OUTPUT_TOKEN_COST = 0.000021

    def __init__(self, config_path="config.json", **kwargs):
        self.full_config = None
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.full_config = json.load(f)
        except FileNotFoundError:
            logger.info("Config file not found: %s. Using default configurations.", config_path)
        except Exception as e:
            logger.warning("Failed to load config file: %s (%s). Using default configurations.", config_path, e)

        if not self.full_config:
            # Fallback/default config if config.json is missing or unreadable
            self.full_config = {
                "api": {
                    "model": "gemini-3.5-live-translate-preview",
                    "target_language": "zh-TW",
                    "subtitle_timeout_seconds": 4.0,
                    "sentence_pause_seconds": 1.5,
                    "idle_reset_seconds": 30.0
                },
                "audio": {
                    "device_name": "BlackHole 2ch",
                    "sample_rate": 16000,
                    "channels": 1
                }
            }
        self.api_config = self.full_config.get("api", {})
        self.audio_config = self.full_config.get("audio", {})
        
        # Override with kwargs if provided for backward compatibility
        if "target_language" in kwargs:
            self.api_config["target_language"] = kwargs["target_language"]
        if "sample_rate" in kwargs:
            self.audio_config["sample_rate"] = kwargs["sample_rate"]
        if "audio_channel_count" in kwargs:
            self.audio_config["channels"] = kwargs["audio_channel_count"]
        if "subtitle_timeout_seconds" in kwargs:
            self.api_config["subtitle_timeout_seconds"] = kwargs["subtitle_timeout_seconds"]
        if "sentence_pause_seconds" in kwargs:
            self.api_config["sentence_pause_seconds"] = kwargs["sentence_pause_seconds"]
        if "idle_reset_seconds" in kwargs:
            self.api_config["idle_reset_seconds"] = kwargs["idle_reset_seconds"]
        if kwargs.get("context_file"):
            self.api_config["context_file"] = kwargs["context_file"]
        self._load_context_file()

        self.client = genai.Client()
        self.model_id = self.api_config.get("model", "gemini-3.5-live-translate-preview")
        self.latest_translation = ""
        self.current_turn_translation = ""
        self.is_new_turn = True
        self.last_activity_time = 0.0
        self.timeout_seconds = self.api_config.get("subtitle_timeout_seconds", 4.0)
        self.pause_threshold = self.api_config.get("sentence_pause_seconds", 1.5)
        self.idle_reset_seconds = self.api_config.get("idle_reset_seconds", 30.0)
        self.session = None
        self.accumulated_prompt_tokens = 0
        self.accumulated_candidates_tokens = 0
        self.current_conn_prompt_tokens = 0
        self.current_conn_candidates_tokens = 0

    def _load_context_file(self):
        """ If api.context_file is set, load {context, glossary} from it (file wins over inline). """
        path = (self.api_config.get("context_file") or "").strip()
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.api_config["context"] = data.get("context", "")
            self.api_config["glossary"] = data.get("glossary", {})
            logger.info("Loaded translation context from %s", path)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to load context_file %s (%s). Ignoring.", path, e)

    def _build_system_instruction(self):
        """ Builds a system_instruction from config `context` + `glossary`, or None.

        The translate model honors translation-biasing guidance (domain context and
        term->translation overrides) but ignores formatting/suppression directives.
        """
        parts = []
        context = (self.api_config.get("context") or "").strip()
        if context:
            parts.append(context)
        glossary = self.api_config.get("glossary") or {}
        if glossary:
            lines = "\n".join(f'- "{term}" -> {tr}' for term, tr in glossary.items() if tr)
            if lines:
                parts.append("Translate these terms consistently:\n" + lines)
        return "\n\n".join(parts) or None

    def get_connect_config(self):
        """ Generates LiveConnectConfig for the Gemini session """
        # TEXT modality: we never play the synthesized audio, so don't pay output-audio rates for it
        cfg = types.LiveConnectConfig(
            response_modalities=[types.Modality.TEXT],
            translation_config=types.TranslationConfig(
                target_language_code=self.api_config.get("target_language", "zh-TW")
            )
        )
        instruction = self._build_system_instruction()
        if instruction:
            cfg.system_instruction = types.Content(parts=[types.Part(text=instruction)])
            logger.info("Using system_instruction (%d chars)", len(instruction))
        return cfg

    @staticmethod
    def _extract_text(content):
        """ Pulls translated text from a server message.

        TEXT modality delivers it via model_turn parts; AUDIO modality via output_transcription.
        """
        if content.model_turn and content.model_turn.parts:
            return "".join(part.text for part in content.model_turn.parts if part.text)
        if content.output_transcription:
            return content.output_transcription.text
        return None

    async def send_audio_loop(self, audio_queue: asyncio.Queue):
        """ Pulls audio chunks from the queue and streams to Gemini Live API """
        try:
            while True:
                chunk = await audio_queue.get()
                if self.session:
                    try:
                        await self.session.send_realtime_input(
                            audio=types.Blob(
                                data=chunk,
                                mime_type=f"audio/pcm;rate={self.audio_config.get('sample_rate', 16000)}"
                            )
                        )
                    except Exception as e:
                        logger.error("Error sending realtime input: %s", e)
                        raise e
                audio_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def receive_translation_loop(self):
        """ Listens for incoming translated text from the WebSocket """
        try:
            sentence_enders = ("。", "？", "！", ".", "?", "!", "\n")
            async for response in self.session.receive():
                # Track token usage and estimated cost
                metadata = getattr(response, "usage_metadata", None)
                if metadata:
                    prompt_tokens = getattr(metadata, "prompt_token_count", 0)
                    candidates_tokens = getattr(metadata, "candidates_token_count", 0)
                    
                    # Ensure they are integers to handle MagicMocks in unit tests
                    if isinstance(prompt_tokens, int) and isinstance(candidates_tokens, int):
                        # Compute deltas
                        delta_prompt = max(0, prompt_tokens - self.current_conn_prompt_tokens)
                        delta_candidates = max(0, candidates_tokens - self.current_conn_candidates_tokens)
                        
                        self.accumulated_prompt_tokens += delta_prompt
                        self.accumulated_candidates_tokens += delta_candidates
                        
                        self.current_conn_prompt_tokens = prompt_tokens
                        self.current_conn_candidates_tokens = candidates_tokens
                        
                        # Estimated cost using class-level pricing constants
                        estimated_cost = (
                            self.accumulated_prompt_tokens * self.PROMPT_TOKEN_COST
                            + self.accumulated_candidates_tokens * self.OUTPUT_TOKEN_COST
                        )
                        
                        logger.info(
                            "Session Accumulated - Prompt Tokens: %d, Candidates Tokens: %d, Estimated Cost: $%.6f",
                            self.accumulated_prompt_tokens,
                            self.accumulated_candidates_tokens,
                            estimated_cost
                        )

                if response.server_content:
                    content = response.server_content
                    
                    # 1. Handle incoming translated text chunks
                    text = self._extract_text(content)
                    if text:
                        current_time = asyncio.get_event_loop().time()

                        # If there was a pause of more than sentence_pause_seconds, start a new turn
                        if self.last_activity_time > 0:
                            pause_duration = current_time - self.last_activity_time
                            if pause_duration > self.pause_threshold:
                                self.is_new_turn = True

                        if self.is_new_turn:
                            self.current_turn_translation = ""
                            self.is_new_turn = False

                        self.current_turn_translation += text
                        self.latest_translation = self.current_turn_translation.strip()
                        self.last_activity_time = current_time
                        logger.info("Translation: %s", self.latest_translation)

                        # Instant split: if the sentence ends with punctuation, mark next turn as new
                        if self.latest_translation.endswith(sentence_enders):
                            logger.info("Sentence boundary punctuation detected. Setting is_new_turn=True.")
                            self.is_new_turn = True

                    # 2. Check if the turn is complete
                    if content.turn_complete:
                        logger.info("Turn complete.")
                        self.is_new_turn = True
                        self.last_activity_time = asyncio.get_event_loop().time()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error receiving from Live session: %s", e)
            raise e

    async def clear_subtitle_timeout_loop(self):
        """ Clears the subtitle overlay if no new translation activity occurs after a timeout """
        try:
            while True:
                await asyncio.sleep(0.5)
                if self.latest_translation and self.last_activity_time:
                    elapsed = asyncio.get_event_loop().time() - self.last_activity_time
                    if elapsed > self.timeout_seconds:
                        logger.info("Subtitle timeout reached. Clearing subtitle overlay.")
                        self.latest_translation = ""
                        self.is_new_turn = True
        except asyncio.CancelledError:
            pass

    async def idle_monitor_loop(self):
        """ Monitors idle time and raises an exception if idle threshold is exceeded to force reset """
        try:
            while True:
                await asyncio.sleep(1.0)
                if self.last_activity_time > 0:
                    idle_duration = asyncio.get_event_loop().time() - self.last_activity_time
                    if idle_duration > self.idle_reset_seconds:
                        logger.info("Session idle for %.1fs (threshold %.1fs). Resetting connection...", idle_duration, self.idle_reset_seconds)
                        raise asyncio.TimeoutError("Session idle timeout exceeded")
        except asyncio.CancelledError:
            pass

    async def connect_and_run(self, audio_queue: asyncio.Queue, on_connect=None, on_disconnect=None):
        """ Establishes connection and handles reconnect loops with exponential backoff """
        connect_config = self.get_connect_config()
        
        initial_delay = 1.0
        max_delay = 60.0
        factor = 2.0
        delay = initial_delay

        while True:
            # Drop audio buffered while disconnected; translating it would show stale subtitles
            while not audio_queue.empty():
                audio_queue.get_nowait()
                audio_queue.task_done()
            try:
                logger.info("Connecting to Gemini Live API...")
                async with self.client.aio.live.connect(
                    model=self.model_id, 
                    config=connect_config
                ) as session:
                    self.session = session
                    logger.info("Connected to Gemini Live successfully.")
                    self.latest_translation = "Listening..."
                    self.last_activity_time = asyncio.get_event_loop().time()

                    if on_connect:
                        try:
                            if asyncio.iscoroutinefunction(on_connect):
                                await on_connect()
                            else:
                                res = on_connect()
                                if asyncio.iscoroutine(res):
                                    await res
                        except Exception as cb_err:
                            logger.error("Error in on_connect callback: %s", cb_err)

                    async def reset_delay_after_stable():
                        try:
                            await asyncio.sleep(5.0)
                            nonlocal delay
                            delay = initial_delay
                            logger.info("Connection stable. Resetting backoff delay.")
                        except asyncio.CancelledError:
                            pass

                    reset_task = asyncio.create_task(reset_delay_after_stable())
                    
                    # Start concurrent send, receive, and clear tasks
                    send_task = asyncio.create_task(self.send_audio_loop(audio_queue))
                    receive_task = asyncio.create_task(self.receive_translation_loop())
                    clear_task = asyncio.create_task(self.clear_subtitle_timeout_loop())
                    
                    tasks = [send_task, receive_task, clear_task]
                    if self.idle_reset_seconds > 0:
                        idle_task = asyncio.create_task(self.idle_monitor_loop())
                        tasks.append(idle_task)
                    else:
                        idle_task = None

                    # Wait for either task to fail/complete
                    done, pending = await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_EXCEPTION
                    )
                    
                    # Cancel the other pending tasks
                    reset_task.cancel()
                    for task in pending:
                        task.cancel()
                    
                    # Propagate exceptions to trigger reconnection
                    for task in done:
                        try:
                            task.result()
                        except asyncio.CancelledError:
                            pass
            except Exception as e:
                logger.error("Session disconnect or connection error: %s. Reconnecting in %.1fs...", e, delay)
                self.latest_translation = f"Reconnecting ({type(e).__name__})..."
                await asyncio.sleep(delay)
                delay = min(delay * factor, max_delay)
            finally:
                self.session = None
                self.current_conn_prompt_tokens = 0
                self.current_conn_candidates_tokens = 0
                if on_disconnect:
                    try:
                        if asyncio.iscoroutinefunction(on_disconnect):
                            await on_disconnect()
                        else:
                            res = on_disconnect()
                            if asyncio.iscoroutine(res):
                                await res
                    except Exception as cb_err:
                        logger.error("Error in on_disconnect callback: %s", cb_err)

    def get_transcription(self):
        """ Returns the latest translation string """
        return self.latest_translation

    def log_session_summary(self):
        """ Logs total token usage and estimated cost for the whole session. """
        cost = (
            self.accumulated_prompt_tokens * self.PROMPT_TOKEN_COST
            + self.accumulated_candidates_tokens * self.OUTPUT_TOKEN_COST
        )
        logger.info(
            "Session summary - prompt tokens: %d, output tokens: %d, estimated cost: $%.2f",
            self.accumulated_prompt_tokens,
            self.accumulated_candidates_tokens,
            cost
        )
