import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import types
from module.transcriber import ContextSwitch, TranscriberTranslator


class TestTranscriberTranslator(unittest.IsolatedAsyncioTestCase):
    """ Test cases for the TranscriberTranslator class using Gemini Live client """

    def setUp(self):
        # Patch genai.Client so that it doesn't try to look up actual environment variables or make network calls.
        self.patcher = patch('google.genai.Client')
        self.mock_client_class = self.patcher.start()
        self.mock_client = self.mock_client_class.return_value

        # Patch builtins.open to raise FileNotFoundError by default for all test cases
        self.open_patcher = patch('builtins.open', side_effect=FileNotFoundError)
        self.mock_open = self.open_patcher.start()

    def tearDown(self):
        self.open_patcher.stop()
        self.patcher.stop()

    @patch("builtins.open", new_callable=unittest.mock.mock_open,
           read_data='{"api": {"model": "test-model", "target_language": "fr-FR"},'
                     ' "audio": {"sample_rate": 8000}}')
    def test_init_with_config(self, mock_file):
        """ Test initialization with a custom config file path """
        translator = TranscriberTranslator("dummy_config.json")
        self.assertEqual(translator.model_id, "test-model")
        self.assertEqual(translator.api_config["target_language"], "fr-FR")
        self.assertEqual(translator.audio_config["sample_rate"], 8000)

    def test_init_with_kwargs(self):
        """ Test initialization with kwargs overriding the config defaults """
        translator = TranscriberTranslator(
            config_path="dummy.json",
            target_language="de-DE",
            audio_channel_count=2
        )
        self.assertEqual(translator.api_config["target_language"], "de-DE")
        self.assertEqual(translator.audio_config["channels"], 2)

    def test_get_connect_config(self):
        """ Test that LiveConnectConfig is constructed correctly """
        translator = TranscriberTranslator(config_path="dummy.json", target_language="es-ES")
        config = translator.get_connect_config()
        self.assertIsInstance(config, types.LiveConnectConfig)
        self.assertEqual(config.translation_config.target_language_code, "es-ES")
        self.assertEqual(config.response_modalities, [types.Modality.TEXT])

    def test_system_instruction_from_context_and_glossary(self):
        """ context + glossary become a system_instruction; empty -> none """
        t = TranscriberTranslator(config_path="dummy.json")
        t.api_config["context"] = ""
        t.api_config["glossary"] = {}
        self.assertIsNone(t._build_system_instruction())
        self.assertIsNone(t.get_connect_config().system_instruction)

        t.api_config["context"] = "Sci-fi drama about hackers."
        t.api_config["glossary"] = {"Neo": "尼歐", "skip": ""}
        instr = t._build_system_instruction()
        self.assertIn("Sci-fi drama about hackers.", instr)
        self.assertIn('"Neo" -> 尼歐', instr)
        self.assertNotIn("skip", instr)  # blank translation dropped
        self.assertEqual(
            t.get_connect_config().system_instruction.parts[0].text, instr)

    @patch("builtins.open", new_callable=unittest.mock.mock_open,
           read_data='{"context": "Show ctx", "glossary": {"A": "甲"}}')
    def test_context_file_loads(self, _mock_file):
        """ context_file populates context/glossary (file wins over inline) """
        t = TranscriberTranslator(config_path="dummy.json", context_file="show.json")
        self.assertEqual(t.api_config["context"], "Show ctx")
        self.assertEqual(t.api_config["glossary"], {"A": "甲"})

    def test_context_file_missing_is_ignored(self):
        """ A missing context_file is ignored, not fatal (setUp makes open raise) """
        t = TranscriberTranslator(config_path="dummy.json", context_file="/no/such.json")
        self.assertIsNone(t._build_system_instruction())

    def test_extract_text_from_model_turn(self):
        """ TEXT modality: text arrives in model_turn parts """
        content = MagicMock()
        part1 = MagicMock()
        part1.text = "Ni"
        part2 = MagicMock()
        part2.text = "Hao"
        content.model_turn.parts = [part1, part2]
        self.assertEqual(TranscriberTranslator._extract_text(content), "NiHao")

    def test_extract_text_falls_back_to_output_transcription(self):
        """ AUDIO modality fallback: text arrives via output_transcription """
        content = MagicMock()
        content.model_turn = None
        content.output_transcription.text = "hello"
        self.assertEqual(TranscriberTranslator._extract_text(content), "hello")

    def test_extract_text_none(self):
        """ No text in the message """
        content = MagicMock()
        content.model_turn = None
        content.output_transcription = None
        self.assertIsNone(TranscriberTranslator._extract_text(content))

    async def test_send_audio_loop(self):
        """ Test that audio loop pulls from the queue and sends through the session """
        translator = TranscriberTranslator(config_path="dummy.json")
        mock_session = AsyncMock()
        translator.session = mock_session

        audio_queue = asyncio.Queue()
        audio_chunk = b'\x00\x01\x02\x03'
        await audio_queue.put(audio_chunk)

        # Start the loop as a task
        loop_task = asyncio.create_task(translator.send_audio_loop(audio_queue))

        # Wait a short moment to let the loop process
        await asyncio.sleep(0.05)

        # Verify send_realtime_input was called with the blob
        mock_session.send_realtime_input.assert_called_once()
        call_kwargs = mock_session.send_realtime_input.call_args[1]
        self.assertIn('audio', call_kwargs)
        self.assertEqual(call_kwargs['audio'].data, audio_chunk)
        self.assertEqual(call_kwargs['audio'].mime_type, "audio/pcm;rate=16000")

        # Cancel task and clean up
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    async def test_receive_translation_loop(self):
        """ Test that receive loop accumulates text chunks and resets on new turns """
        translator = TranscriberTranslator(config_path="dummy.json")
        mock_session = MagicMock()
        translator.session = mock_session

        # Mock responses from receive() async generator
        mock_response_1 = MagicMock()
        mock_response_1.server_content = MagicMock()
        mock_response_1.server_content.model_turn = None
        mock_response_1.server_content.output_transcription = MagicMock()
        mock_response_1.server_content.output_transcription.text = "Hello"
        mock_response_1.server_content.turn_complete = False

        mock_response_2 = MagicMock()
        mock_response_2.server_content = None  # should be ignored

        mock_response_3 = MagicMock()
        mock_response_3.server_content = MagicMock()
        mock_response_3.server_content.model_turn = None
        mock_response_3.server_content.output_transcription = None  # should be ignored
        mock_response_3.server_content.turn_complete = False

        mock_response_4 = MagicMock()
        mock_response_4.server_content = MagicMock()
        mock_response_4.server_content.model_turn = None
        mock_response_4.server_content.output_transcription = MagicMock()
        mock_response_4.server_content.output_transcription.text = " World"
        mock_response_4.server_content.turn_complete = False

        # Turn completion message
        mock_response_5 = MagicMock()
        mock_response_5.server_content = MagicMock()
        mock_response_5.server_content.model_turn = None
        mock_response_5.server_content.output_transcription = None
        mock_response_5.server_content.turn_complete = True

        # Next turn starts
        mock_response_6 = MagicMock()
        mock_response_6.server_content = MagicMock()
        mock_response_6.server_content.model_turn = None
        mock_response_6.server_content.output_transcription = MagicMock()
        mock_response_6.server_content.output_transcription.text = "New Sentence"
        mock_response_6.server_content.turn_complete = False

        async def mock_receive_generator():
            yield mock_response_1
            yield mock_response_2
            yield mock_response_3
            yield mock_response_4
            # Verify accumulation before turn completion
            await asyncio.sleep(0.02)
            yield mock_response_5
            await asyncio.sleep(0.02)
            yield mock_response_6
            # Keep open to simulate active connection
            while True:
                await asyncio.sleep(1)

        mock_session.receive = MagicMock(return_value=mock_receive_generator())

        loop_task = asyncio.create_task(translator.receive_translation_loop())

        # Wait a short moment to let generator process response 1-4
        await asyncio.sleep(0.01)
        self.assertEqual(translator.get_transcription(), "Hello World")

        # Wait for turn complete (response 5) and new sentence (response 6)
        await asyncio.sleep(0.05)
        self.assertEqual(translator.get_transcription(), "New Sentence")

        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    async def test_clear_subtitle_timeout_loop(self):
        """ Test that clear loop resets translation after silence """
        translator = TranscriberTranslator(config_path="dummy.json", subtitle_timeout_seconds=0.1)
        translator.latest_translation = "Some subtitle text"
        translator.is_new_turn = False
        translator.last_activity_time = asyncio.get_event_loop().time() - 0.2  # exceeded 0.1s

        clear_task = asyncio.create_task(translator.clear_subtitle_timeout_loop())
        await asyncio.sleep(0.6)  # let it run once (since it sleeps 0.5s)

        self.assertEqual(translator.get_transcription(), "")
        self.assertTrue(translator.is_new_turn)

        clear_task.cancel()
        try:
            await clear_task
        except asyncio.CancelledError:
            pass

    async def test_receive_translation_loop_temporal_pause(self):
        """ Test that receive loop resets turn and starts new sentence when pause threshold exceeded """
        translator = TranscriberTranslator(config_path="dummy.json", sentence_pause_seconds=0.1)
        mock_session = MagicMock()
        translator.session = mock_session

        mock_response_1 = MagicMock()
        mock_response_1.server_content = MagicMock()
        mock_response_1.server_content.model_turn = None
        mock_response_1.server_content.output_transcription = MagicMock()
        mock_response_1.server_content.output_transcription.text = "Hello"
        mock_response_1.server_content.turn_complete = False

        mock_response_2 = MagicMock()
        mock_response_2.server_content = MagicMock()
        mock_response_2.server_content.model_turn = None
        mock_response_2.server_content.output_transcription = MagicMock()
        mock_response_2.server_content.output_transcription.text = "New Turn"
        mock_response_2.server_content.turn_complete = False

        async def mock_receive_generator():
            yield mock_response_1
            # Wait longer than 0.1s to exceed pause_threshold
            await asyncio.sleep(0.15)
            yield mock_response_2
            while True:
                await asyncio.sleep(1)

        mock_session.receive = MagicMock(return_value=mock_receive_generator())

        loop_task = asyncio.create_task(translator.receive_translation_loop())

        # Check first chunk
        await asyncio.sleep(0.02)
        self.assertEqual(translator.get_transcription(), "Hello")

        # Check second chunk starts a new turn because of temporal pause
        await asyncio.sleep(0.15)
        self.assertEqual(translator.get_transcription(), "New Turn")

        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    async def test_receive_translation_loop_punctuation_split(self):
        """ Test that receive loop resets turn immediately when sentence-ending punctuation is received """
        translator = TranscriberTranslator(config_path="dummy.json")
        mock_session = MagicMock()
        translator.session = mock_session

        mock_response_1 = MagicMock()
        mock_response_1.server_content = MagicMock()
        mock_response_1.server_content.model_turn = None
        mock_response_1.server_content.output_transcription = MagicMock()
        mock_response_1.server_content.output_transcription.text = "你好。"
        mock_response_1.server_content.turn_complete = False

        mock_response_2 = MagicMock()
        mock_response_2.server_content = MagicMock()
        mock_response_2.server_content.model_turn = None
        mock_response_2.server_content.output_transcription = MagicMock()
        mock_response_2.server_content.output_transcription.text = "吃飽了嗎？"
        mock_response_2.server_content.turn_complete = False

        mock_response_3 = MagicMock()
        mock_response_3.server_content = MagicMock()
        mock_response_3.server_content.model_turn = None
        mock_response_3.server_content.output_transcription = MagicMock()
        mock_response_3.server_content.output_transcription.text = "好的"
        mock_response_3.server_content.turn_complete = False

        async def mock_receive_generator():
            yield mock_response_1
            await asyncio.sleep(0.01)
            yield mock_response_2
            await asyncio.sleep(0.01)
            yield mock_response_3
            while True:
                await asyncio.sleep(1)

        mock_session.receive = MagicMock(return_value=mock_receive_generator())

        loop_task = asyncio.create_task(translator.receive_translation_loop())

        # Check first sentence ends with 。 and splits immediately
        await asyncio.sleep(0.005)
        self.assertEqual(translator.get_transcription(), "你好。")
        self.assertTrue(translator.is_new_turn)  # should be set to True instantly

        # Check second sentence begins fresh and accumulates, then splits on ？
        await asyncio.sleep(0.015)
        self.assertEqual(translator.get_transcription(), "吃飽了嗎？")
        self.assertTrue(translator.is_new_turn)

        # Check third sentence begins fresh and accumulates
        await asyncio.sleep(0.015)
        self.assertEqual(translator.get_transcription(), "好的")
        self.assertFalse(translator.is_new_turn)  # no punctuation ender, so False

        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    async def test_connect_and_run_success_and_reconnect(self):
        """ Test connection establishment, running loops, error handling, and reconnection """
        translator = TranscriberTranslator(config_path="dummy.json")

        # Mock connection context manager
        mock_session = MagicMock()
        mock_session.send_realtime_input = AsyncMock()
        # Mock receive to raise exception to trigger reconnect
        mock_session.receive = MagicMock(side_effect=ConnectionResetError("Connection closed by peer"))

        mock_connect_cm = AsyncMock()
        mock_connect_cm.__aenter__.return_value = mock_session

        translator.client.aio.live.connect.return_value = mock_connect_cm

        audio_queue = asyncio.Queue()

        # Run connect_and_run, but mock asyncio.sleep in module.transcriber so we don't actually wait during reconnect
        real_sleep = asyncio.sleep
        sleep_calls = []

        async def mock_sleep(d):
            sleep_calls.append(d)
            if d == 1.0:  # Reconnect delay sleep call
                raise asyncio.CancelledError("Exiting reconnect loop for test")
            await real_sleep(0.0)  # Yield control

        with patch('module.transcriber.asyncio.sleep', side_effect=mock_sleep):
            # We let the run loop run for a bit
            run_task = asyncio.create_task(translator.connect_and_run(audio_queue))

            # Wait a short moment to let it run
            try:
                await run_task
            except asyncio.CancelledError:
                pass

            # Verify we attempted to connect to Gemini Live
            translator.client.aio.live.connect.assert_called()

            # Verify we updated the status to Reconnecting... with the exception class
            self.assertEqual(translator.get_transcription(), "Reconnecting (ConnectionResetError)...")

            # Verify mock_sleep was called with stable wait first, then reconnect backoff delay
            self.assertIn(5.0, sleep_calls)  # stable check sleep
            self.assertIn(1.0, sleep_calls)  # reconnect backoff sleep

    async def test_token_usage_accumulation(self):
        """ Test that token usage is accumulated and deltas are calculated correctly """
        translator = TranscriberTranslator(config_path="dummy.json")
        mock_session = MagicMock()
        translator.session = mock_session

        # Real UsageMetadata, not a MagicMock: the field names have to be the ones the
        # Live API actually sends, or this test passes while the accounting reads nothing.
        mock_metadata_1 = types.UsageMetadata(prompt_token_count=100, response_token_count=10)
        mock_metadata_2 = types.UsageMetadata(prompt_token_count=150, response_token_count=25)

        mock_response_1 = MagicMock()
        mock_response_1.server_content = None
        mock_response_1.usage_metadata = mock_metadata_1

        mock_response_2 = MagicMock()
        mock_response_2.server_content = None
        mock_response_2.usage_metadata = mock_metadata_2

        async def mock_receive():
            yield mock_response_1
            yield mock_response_2
            while True:
                await asyncio.sleep(1)

        mock_session.receive = MagicMock(return_value=mock_receive())

        loop_task = asyncio.create_task(translator.receive_translation_loop())
        await asyncio.sleep(0.05)

        self.assertEqual(translator.accumulated_prompt_tokens, 150)
        self.assertEqual(translator.accumulated_output_tokens, 25)

        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    async def test_thought_tokens_billed_as_output(self):
        """ thoughts_token_count bills at the output rate and is reported separately from
        response_token_count; counting only the latter under-reports the expensive half. """
        translator = TranscriberTranslator(config_path="dummy.json")
        translator._account_tokens(
            types.UsageMetadata(prompt_token_count=100, response_token_count=10, thoughts_token_count=40)
        )
        self.assertEqual(translator.accumulated_output_tokens, 50)

    def test_turn_text_capped_keeping_the_tail(self):
        """ The overlay clips overflow at the bottom, so a runaway turn must shed its head,
        not its tail - the tail is the newest text. """
        translator = TranscriberTranslator(config_path="dummy.json")
        translator.is_new_turn = True
        translator._append_translation("x" * (TranscriberTranslator.MAX_TURN_CHARS + 50))
        translator._append_translation("END")

        self.assertEqual(len(translator.latest_translation), TranscriberTranslator.MAX_TURN_CHARS)
        self.assertTrue(translator.latest_translation.endswith("END"))

    async def test_capture_stops_before_reconnect_backoff(self):
        """ on_disconnect must fire before the backoff sleep. Sleeping first left PortAudio
        running for up to max_delay seconds with nothing draining the queue. """
        # idle monitor off: its own sleep(1.0) would otherwise collide with the backoff below
        translator = TranscriberTranslator(config_path="dummy.json", idle_reset_seconds=0)

        mock_session = MagicMock()
        mock_session.receive = MagicMock(side_effect=ConnectionResetError("dropped"))
        mock_connect_cm = AsyncMock()
        mock_connect_cm.__aenter__.return_value = mock_session
        translator.client.aio.live.connect.return_value = mock_connect_cm

        real_sleep = asyncio.sleep
        events = []

        async def mock_sleep(d):
            events.append(f"sleep:{d}")
            if d == 1.0:  # the backoff
                raise asyncio.CancelledError("stop the loop")
            await real_sleep(0.0)

        with patch('module.transcriber.asyncio.sleep', side_effect=mock_sleep):
            try:
                await translator.connect_and_run(
                    asyncio.Queue(), on_disconnect=lambda: events.append("stop_stream")
                )
            except asyncio.CancelledError:
                pass

        self.assertIn("stop_stream", events)
        self.assertLess(events.index("stop_stream"), events.index("sleep:1.0"))

    async def test_idle_monitor_ignores_quiet_source(self):
        """ A quiet source must not force a reconnect: the gate sends nothing, so nothing
        is unanswered. This used to paint "Reconnecting..." over every silent passage. """
        translator = TranscriberTranslator(config_path="dummy.json", idle_reset_seconds=0.05)
        now = asyncio.get_event_loop().time()
        translator.last_activity_time = now - 10.0   # no translation for ages...
        translator.last_sent_time = now - 10.5       # ...because no audio was sent either

        real_sleep = asyncio.sleep

        async def fast_sleep(_delay):
            await real_sleep(0.001)

        with patch('module.transcriber.asyncio.sleep', side_effect=fast_sleep):
            task = asyncio.create_task(translator.idle_monitor_loop())
            await real_sleep(0.05)
            self.assertFalse(task.done(), "quiet source must not trigger a reconnect")
            task.cancel()

    async def test_idle_monitor_resets_when_audio_goes_unanswered(self):
        """ Audio streaming out with no translation coming back is a wedged stream """
        translator = TranscriberTranslator(config_path="dummy.json", idle_reset_seconds=0.05)
        now = asyncio.get_event_loop().time()
        translator.last_activity_time = now - 10.0   # no translation for ages...
        translator.last_sent_time = now             # ...but audio is still going out

        real_sleep = asyncio.sleep

        async def fast_sleep(_delay):
            await real_sleep(0.001)

        with patch('module.transcriber.asyncio.sleep', side_effect=fast_sleep):
            with self.assertRaises(asyncio.TimeoutError):
                await translator.idle_monitor_loop()

    async def test_connect_and_run_drains_stale_queue(self):
        """ Audio buffered while disconnected must be dropped, not streamed on reconnect """
        translator = TranscriberTranslator(config_path="dummy.json")
        queue = asyncio.Queue()
        for _ in range(3):
            queue.put_nowait(b'stale')

        # First connect attempt raises; patched sleep aborts the retry loop.
        translator.client.aio.live.connect = MagicMock(side_effect=RuntimeError("boom"))

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await translator.connect_and_run(queue)

        self.assertTrue(queue.empty())

    async def test_connection_error_shows_exception_on_overlay(self):
        """ Connection failures must surface the exception class, not a bare Reconnecting """
        translator = TranscriberTranslator(config_path="dummy.json")
        translator.client.aio.live.connect = MagicMock(side_effect=ValueError("bad key"))

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await translator.connect_and_run(asyncio.Queue())

        self.assertIn("Reconnecting", translator.latest_translation)
        self.assertIn("ValueError", translator.latest_translation)

    @patch("builtins.open", new_callable=unittest.mock.mock_open,
           read_data='{"context": "Space opera.", "glossary": {"Ship": "船"}}')
    async def test_context_switch_reconnects_with_new_instruction(self, _mock_file):
        """ Switching context mid-run: the live session is dropped, and the next connect
        carries the new system_instruction (the config used to be built once, before the
        reconnect loop, so a switch never reached the API). """
        translator = TranscriberTranslator(config_path="dummy.json")
        self.assertIsNone(translator.get_connect_config().system_instruction)

        configs = []
        real_sleep = asyncio.sleep

        def fake_connect(model=None, config=None):
            configs.append(config)
            if len(configs) == 1:
                translator.set_context_file("contexts/space.json")  # user picks it from the menu
            raise RuntimeError("boom")

        async def stop_after_two(_delay):
            if len(configs) >= 2:
                raise asyncio.CancelledError
            await real_sleep(0)

        translator.client.aio.live.connect = MagicMock(side_effect=fake_connect)
        with patch("module.transcriber.asyncio.sleep", stop_after_two):
            with self.assertRaises(asyncio.CancelledError):
                await translator.connect_and_run(asyncio.Queue())

        self.assertIsNone(configs[0].system_instruction)
        self.assertIn("Space opera.", configs[1].system_instruction.parts[0].text)

        # And the running session gets torn down rather than waiting for the next dropout.
        translator.set_context_file("contexts/space.json")
        with patch("module.transcriber.asyncio.sleep", lambda _d: real_sleep(0)):
            with self.assertRaises(ContextSwitch):
                await asyncio.wait_for(translator.context_switch_loop(), 1.0)

    def test_log_session_summary(self):
        """ Shutdown summary logs accumulated tokens and cost """
        translator = TranscriberTranslator(config_path="dummy.json")
        translator.accumulated_prompt_tokens = 1000000
        translator.accumulated_output_tokens = 1000000
        with patch('module.transcriber.logger.info') as mock_info:
            translator.log_session_summary()
            mock_info.assert_called_once()
            logged = mock_info.call_args[0][0] % tuple(mock_info.call_args[0][1:])
        self.assertIn("1000000", logged)
        self.assertIn("24.50", logged)  # 3.50 input + 21.00 output per 1M tokens


if __name__ == '__main__':
    unittest.main()
