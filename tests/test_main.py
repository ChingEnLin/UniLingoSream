""" Test cases for the main integration script """
import unittest
from unittest.mock import MagicMock, patch
import asyncio

from main import run_async_loop, poll_transcription, POLL_INTERVAL_MS

class TestMain(unittest.TestCase):
    """ Test cases for main.py integration """

    def test_run_async_loop(self):
        """ Test run_async_loop starts the stream, runs loop, and stops stream """
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        mock_queue = MagicMock()
        mock_transcriber = MagicMock()
        mock_capturer = MagicMock()

        run_async_loop(mock_loop, mock_queue, mock_transcriber, mock_capturer)

        mock_capturer.start_stream.assert_called_once()
        mock_loop.run_until_complete.assert_called_once_with(
            mock_transcriber.connect_and_run(mock_queue)
        )
        mock_capturer.stop_stream.assert_called_once()
        mock_loop.close.assert_called_once()

    def test_run_async_loop_exception(self):
        """ Test run_async_loop exception handling ensures stop_stream is called """
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        mock_queue = MagicMock()
        mock_transcriber = MagicMock()
        mock_capturer = MagicMock()

        mock_loop.run_until_complete.side_effect = Exception("Test async exception")

        with patch('main.logger.error') as mock_log_err:
            run_async_loop(mock_loop, mock_queue, mock_transcriber, mock_capturer)
            mock_log_err.assert_called_once()

        mock_capturer.start_stream.assert_called_once()
        mock_capturer.stop_stream.assert_called_once()
        mock_loop.close.assert_called_once()

    def test_poll_transcription_with_text(self):
        """ Test poll_transcription updates label when transcription changed """
        mock_display = MagicMock()
        mock_transcriber = MagicMock()
        mock_transcriber.get_transcription.return_value = "Hello"

        poll_transcription(mock_display, mock_transcriber)

        mock_display.update_label.assert_called_once_with("Hello")
        mock_display.root.after.assert_called_once_with(
            POLL_INTERVAL_MS, poll_transcription, mock_display, mock_transcriber, "Hello"
        )

    def test_poll_transcription_no_text(self):
        """ Test poll_transcription does not re-render when nothing changed """
        mock_display = MagicMock()
        mock_transcriber = MagicMock()
        mock_transcriber.get_transcription.return_value = ""

        poll_transcription(mock_display, mock_transcriber)

        mock_display.update_label.assert_not_called()
        mock_display.root.after.assert_called_once_with(
            POLL_INTERVAL_MS, poll_transcription, mock_display, mock_transcriber, ""
        )

    def test_poll_transcription_clears_label(self):
        """ Timeout-cleared translation ("") must reach the screen """
        mock_display = MagicMock()
        mock_transcriber = MagicMock()
        mock_transcriber.get_transcription.return_value = ""

        poll_transcription(mock_display, mock_transcriber, last_rendered="Hello")

        mock_display.update_label.assert_called_once_with("")

    def test_poll_transcription_skips_identical_text(self):
        """ Unchanged text must not be re-rendered every 50ms """
        mock_display = MagicMock()
        mock_transcriber = MagicMock()
        mock_transcriber.get_transcription.return_value = "Hello"

        poll_transcription(mock_display, mock_transcriber, last_rendered="Hello")

        mock_display.update_label.assert_not_called()

    @patch('module.transcriber.TranscriberTranslator')
    @patch('module.audio_capturer.AudioCapturer')
    @patch('module.display.DisplayTranslation')
    @patch('threading.Thread')
    @patch('asyncio.new_event_loop')
    @patch('asyncio.Queue')
    @patch('os.getenv')
    def test_main_execution_success(
        self, mock_getenv, mock_queue_class, mock_new_loop, 
        mock_thread_class, mock_display_class, mock_capturer_class, mock_transcriber_class
    ):
        """ Test that the main execution flows correctly when API key is found """
        mock_getenv.return_value = "fake-api-key"
        mock_new_loop.return_value = MagicMock(spec=asyncio.AbstractEventLoop)
        
        import runpy
        runpy.run_path("main.py", run_name="__main__")
        
        mock_transcriber_class.assert_called_once()
        mock_capturer_class.assert_called_once()
        mock_display_class.assert_called_once()
        mock_thread_class.assert_called_once()
        
        # Verify daemon is True
        kwargs = mock_thread_class.call_args[1]
        self.assertTrue(kwargs.get('daemon'))
        
        # Verify Tkinter GUI is started
        mock_display_class.return_value.start_gui.assert_called_once()

        from main import AUDIO_QUEUE_MAXSIZE
        mock_queue_class.assert_called_once_with(maxsize=AUDIO_QUEUE_MAXSIZE)

        mock_display_class.return_value.update_label.assert_not_called()

    @patch('module.transcriber.TranscriberTranslator')
    @patch('module.audio_capturer.AudioCapturer')
    @patch('module.display.DisplayTranslation')
    @patch('threading.Thread')
    @patch('asyncio.new_event_loop')
    @patch('asyncio.Queue')
    @patch('os.getenv')
    def test_main_warns_on_device_fallback(
        self, mock_getenv, mock_queue_class, mock_new_loop,
        mock_thread_class, mock_display_class, mock_capturer_class, mock_transcriber_class
    ):
        """ Missing BlackHole must produce a visible overlay warning """
        mock_getenv.return_value = "fake-api-key"
        mock_new_loop.return_value = MagicMock(spec=asyncio.AbstractEventLoop)
        mock_capturer_class.return_value.device_index = None
        mock_capturer_class.return_value.device_name = "BlackHole 2ch"

        import runpy
        runpy.run_path("main.py", run_name="__main__")

        warning = mock_display_class.return_value.update_label.call_args[0][0]
        self.assertIn("WARNING", warning)
        self.assertIn("BlackHole 2ch", warning)

    @patch('module.transcriber.TranscriberTranslator')
    @patch('module.audio_capturer.AudioCapturer')
    @patch('module.display.DisplayTranslation')
    @patch('os.getenv')
    def test_main_execution_missing_api_key(
        self, mock_getenv, mock_display_class, mock_capturer_class, mock_transcriber_class
    ):
        """ Test that the main execution exits with error when API key is missing """
        mock_getenv.return_value = None
        
        import runpy
        with patch('main.logger.error') as mock_log_err:
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path("main.py", run_name="__main__")
            self.assertEqual(cm.exception.code, 1)
            mock_log_err.assert_called_once()

if __name__ == '__main__':
    unittest.main()
