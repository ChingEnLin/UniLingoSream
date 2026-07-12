import asyncio
import logging
import json
from google import genai
from google.genai import types

logger = logging.getLogger('root')

class TranscriberTranslator:
    """ Transcriber module for transcribing and translating audio data using Gemini Live Client """
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
                    "source_language": "ja-JP",
                    "target_language": "zh-TW",
                    "subtitle_timeout_seconds": 4.0
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
        if "source_language" in kwargs:
            self.api_config["source_language"] = kwargs["source_language"]
        if "sample_rate" in kwargs:
            self.audio_config["sample_rate"] = kwargs["sample_rate"]
        if "audio_channel_count" in kwargs:
            self.audio_config["channels"] = kwargs["audio_channel_count"]
        if "subtitle_timeout_seconds" in kwargs:
            self.api_config["subtitle_timeout_seconds"] = kwargs["subtitle_timeout_seconds"]

        self.client = genai.Client()
        self.model_id = self.api_config.get("model", "gemini-3.5-live-translate-preview")
        self.latest_translation = ""
        self.current_turn_translation = ""
        self.is_new_turn = True
        self.last_activity_time = 0.0
        self.timeout_seconds = self.api_config.get("subtitle_timeout_seconds", 4.0)
        self.session = None

    def get_connect_config(self):
        """ Generates LiveConnectConfig for the Gemini session """
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            translation_config=types.TranslationConfig(
                target_language_code=self.api_config.get("target_language", "zh-TW")
            ),
            output_audio_transcription=types.AudioTranscriptionConfig()
        )

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
            async for response in self.session.receive():
                if response.server_content:
                    content = response.server_content
                    
                    # 1. Handle incoming text transcription chunks
                    if content.output_transcription:
                        text = content.output_transcription.text
                        if text:
                            if self.is_new_turn:
                                self.current_turn_translation = ""
                                self.is_new_turn = False
                            
                            self.current_turn_translation += text
                            self.latest_translation = self.current_turn_translation.strip()
                            self.last_activity_time = asyncio.get_event_loop().time()
                            logger.info("Translation: %s", self.latest_translation)
                            
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
        """ Clears the subtitle overlay if no new translation activity occurs after a turn is complete """
        try:
            while True:
                await asyncio.sleep(0.5)
                if self.is_new_turn and self.latest_translation and self.last_activity_time:
                    elapsed = asyncio.get_event_loop().time() - self.last_activity_time
                    if elapsed > self.timeout_seconds:
                        logger.info("Subtitle timeout reached. Clearing subtitle overlay.")
                        self.latest_translation = ""
        except asyncio.CancelledError:
            pass

    async def connect_and_run(self, audio_queue: asyncio.Queue):
        """ Establishes connection and handles reconnect loops with exponential backoff """
        connect_config = self.get_connect_config()
        
        initial_delay = 1.0
        max_delay = 60.0
        factor = 2.0
        delay = initial_delay

        while True:
            try:
                logger.info("Connecting to Gemini Live API...")
                async with self.client.aio.live.connect(
                    model=self.model_id, 
                    config=connect_config
                ) as session:
                    self.session = session
                    logger.info("Connected to Gemini Live successfully.")
                    
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
                    
                    # Wait for either task to fail/complete
                    done, pending = await asyncio.wait(
                        [send_task, receive_task, clear_task],
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
                self.latest_translation = "Reconnecting..."
                await asyncio.sleep(delay)
                delay = min(delay * factor, max_delay)
            finally:
                self.session = None

    def get_transcription(self):
        """ Returns the latest translation string """
        return self.latest_translation
