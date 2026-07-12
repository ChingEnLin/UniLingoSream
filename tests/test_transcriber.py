import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import types
from module.transcriber import TranscriberTranslator

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

    @patch("builtins.open", new_callable=unittest.mock.mock_open, read_data='{"api": {"model": "test-model", "target_language": "fr-FR"}, "audio": {"sample_rate": 8000}}')
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
        self.assertEqual(config.response_modalities, [types.Modality.AUDIO])

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
        mock_response_1.server_content.output_transcription = MagicMock()
        mock_response_1.server_content.output_transcription.text = "Hello"
        mock_response_1.server_content.turn_complete = False
        
        mock_response_2 = MagicMock()
        mock_response_2.server_content = None # should be ignored
        
        mock_response_3 = MagicMock()
        mock_response_3.server_content = MagicMock()
        mock_response_3.server_content.output_transcription = None # should be ignored
        mock_response_3.server_content.turn_complete = False
        
        mock_response_4 = MagicMock()
        mock_response_4.server_content = MagicMock()
        mock_response_4.server_content.output_transcription = MagicMock()
        mock_response_4.server_content.output_transcription.text = " World"
        mock_response_4.server_content.turn_complete = False

        # Turn completion message
        mock_response_5 = MagicMock()
        mock_response_5.server_content = MagicMock()
        mock_response_5.server_content.output_transcription = None
        mock_response_5.server_content.turn_complete = True

        # Next turn starts
        mock_response_6 = MagicMock()
        mock_response_6.server_content = MagicMock()
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
        translator.last_activity_time = asyncio.get_event_loop().time() - 0.2 # exceeded 0.1s
        
        clear_task = asyncio.create_task(translator.clear_subtitle_timeout_loop())
        await asyncio.sleep(0.6) # let it run once (since it sleeps 0.5s)
        
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
        mock_response_1.server_content.output_transcription = MagicMock()
        mock_response_1.server_content.output_transcription.text = "Hello"
        mock_response_1.server_content.turn_complete = False
        
        mock_response_2 = MagicMock()
        mock_response_2.server_content = MagicMock()
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
        mock_response_1.server_content.output_transcription = MagicMock()
        mock_response_1.server_content.output_transcription.text = "你好。"
        mock_response_1.server_content.turn_complete = False
        
        mock_response_2 = MagicMock()
        mock_response_2.server_content = MagicMock()
        mock_response_2.server_content.output_transcription = MagicMock()
        mock_response_2.server_content.output_transcription.text = "吃飽了嗎？"
        mock_response_2.server_content.turn_complete = False

        mock_response_3 = MagicMock()
        mock_response_3.server_content = MagicMock()
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
        self.assertTrue(translator.is_new_turn) # should be set to True instantly
        
        # Check second sentence begins fresh and accumulates, then splits on ？
        await asyncio.sleep(0.015)
        self.assertEqual(translator.get_transcription(), "吃飽了嗎？")
        self.assertTrue(translator.is_new_turn)
        
        # Check third sentence begins fresh and accumulates
        await asyncio.sleep(0.015)
        self.assertEqual(translator.get_transcription(), "好的")
        self.assertFalse(translator.is_new_turn) # no punctuation ender, so False
        
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
            if d == 1.0: # Reconnect delay sleep call
                raise asyncio.CancelledError("Exiting reconnect loop for test")
            await real_sleep(0.0) # Yield control
            
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
            
            # Verify we updated the status to Reconnecting...
            self.assertEqual(translator.get_transcription(), "Reconnecting...")
            
            # Verify mock_sleep was called with stable wait first, then reconnect backoff delay
            self.assertIn(5.0, sleep_calls) # stable check sleep
            self.assertIn(1.0, sleep_calls) # reconnect backoff sleep

if __name__ == '__main__':
    unittest.main()