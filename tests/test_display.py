""" Test cases for the DisplayTranslation class """
import unittest
from unittest.mock import MagicMock
from module.display import DisplayTranslation

class TestDisplayTranslation(unittest.TestCase):
    """ Test cases for the DisplayTranslation class """

    def setUp(self):
        """ Set up the DisplayTranslation instance """
        self.display = DisplayTranslation()

    def test_update_label(self):
        """ Test updating the label with a new translation """
        new_translation = "Hello, world!"
        self.display.update_label(new_translation)
        self.assertEqual(self.display.label.cget("text"), new_translation)

    def test_start_gui(self):
        """ Test starting the Tkinter GUI loop """
        # Mock the mainloop method of the root window
        self.display.root.mainloop = MagicMock()
        self.display.start_gui()
        self.display.root.mainloop.assert_called_once()

if __name__ == '__main__':
    unittest.main()