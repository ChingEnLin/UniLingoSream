""" Test cases for the DisplayTranslation class """
import unittest
from unittest.mock import MagicMock, patch
from module.display import DisplayTranslation


class TestDisplayTranslation(unittest.TestCase):
    """ Test cases for the DisplayTranslation class """

    def setUp(self):
        """ Set up the DisplayTranslation instance with mocks to avoid live Tkinter windows """
        self.mock_root = MagicMock()
        self.mock_root.winfo_screenwidth.return_value = 1920
        self.mock_root.winfo_screenheight.return_value = 1080

        # Patch tkinter.Label so it doesn't try to instantiate a real UI component
        self.label_patcher = patch('module.display.tk.Label')
        self.mock_label_class = self.label_patcher.start()
        self.mock_label_instance = MagicMock()
        self.mock_label_class.return_value = self.mock_label_instance

        # Patch tkinter.Menu so it doesn't try to instantiate a real UI component
        self.menu_patcher = patch('module.display.tk.Menu')
        self.mock_menu_class = self.menu_patcher.start()
        self.mock_menu_instance = MagicMock()
        self.mock_menu_class.return_value = self.mock_menu_instance

        self.display = DisplayTranslation(root=self.mock_root, config={})

        self.mock_root.winfo_height.return_value = 90
        self.mock_root.winfo_width.return_value = 1536
        self.mock_root.winfo_x.return_value = 192
        self.mock_root.winfo_y.return_value = 890
        self.mock_label_instance.winfo_reqheight.return_value = 70
        self.mock_root.geometry.reset_mock()

    def tearDown(self):
        self.label_patcher.stop()
        self.menu_patcher.stop()

    def test_update_label(self):
        """ Test updating the label with a new translation """
        new_translation = "Hello, world!"
        self.display.update_label(new_translation)
        self.mock_label_instance.config.assert_called_once_with(text=new_translation)

    def test_update_label_grows_window_for_long_text(self):
        """ Window grows (bottom-anchored) when the label needs more height """
        self.mock_label_instance.winfo_reqheight.return_value = 160
        self.display.update_label("a very long translation that wraps to several lines")
        self.mock_root.geometry.assert_called_with("1536x180+192+800")

    def test_update_label_keeps_base_height_for_short_text(self):
        """ Short text keeps the configured base height: no resize call """
        self.mock_label_instance.winfo_reqheight.return_value = 70
        self.display.update_label("short")
        self.mock_root.geometry.assert_not_called()

    def test_end_drag_persists_position(self):
        """ Releasing a drag writes window_x/window_y back to config.json """
        import json as jsonlib
        from unittest.mock import mock_open
        self.mock_root.winfo_x.return_value = 300
        self.mock_root.winfo_y.return_value = 500
        m = mock_open(read_data='{"ui": {}}')
        with patch("module.display.open", m):
            self.display.end_drag(MagicMock())
        written = "".join(call.args[0] for call in m().write.call_args_list)
        data = jsonlib.loads(written)
        self.assertEqual(data["ui"]["window_x"], 300)
        self.assertEqual(data["ui"]["window_y"], 500)

    def test_saved_position_used_at_startup(self):
        """ A persisted position overrides the computed centered position """
        DisplayTranslation(root=self.mock_root, config={"window_x": 10, "window_y": 20})
        geometry_arg = self.mock_root.geometry.call_args_list[0].args[0]
        self.assertTrue(geometry_arg.endswith("+10+20"))

    def test_start_gui(self):
        """ Test starting the Tkinter GUI loop """
        self.display.start_gui()
        self.mock_root.mainloop.assert_called_once()

    def test_config_ui_attributes(self):
        """ Test that UI attributes match the configuration """
        test_config = {
            "font_family": "Arial",
            "font_size": 18,
            "text_color": "#FF0000",
            "bg_color": "#111111",
            "bg_opacity": 0.5,
            "window_height": 100,
            "window_width_percent": 75,
            "bottom_margin": 50,
            "always_on_top": False,
            "draggable": True
        }

        display = DisplayTranslation(root=self.mock_root, config=test_config)
        self.assertIsNotNone(display)

        # Verify attributes on root mock
        self.mock_root.overrideredirect.assert_called_with(True)
        self.mock_root.attributes.assert_any_call("-alpha", 0.5)
        self.mock_root.wm_attributes.assert_any_call("-topmost", False)
        self.mock_root.configure.assert_any_call(bg="#111111")

        # Verify label creation params
        self.mock_label_class.assert_called_with(
            self.mock_root,
            text="Waiting for translation...",
            font=("Arial", 18),
            fg="#FF0000",
            bg="#111111",
            wraplength=1400,  # 1920 * 75 / 100 - 40 = 1440 - 40 = 1400
            justify="center"
        )

    def test_default_config_fallback(self):
        """ Test fallback to default config when file path is invalid """
        display = DisplayTranslation(config_path="nonexistent_file.json", root=self.mock_root)
        self.assertEqual(display.config["font_family"], "Helvetica")
        self.assertEqual(display.config["font_size"], 24)
        self.assertEqual(display.config["bg_color"], "#000000")

    def test_drag(self):
        """ Test dragging the window updates its geometry coordinates """
        # Start drag at (10, 20) using MagicMock for events
        event_start = MagicMock(x=10, y=20)
        self.display.start_drag(event_start)
        self.assertEqual(self.display._drag_data["x"], 10)
        self.assertEqual(self.display._drag_data["y"], 20)

        # Drag to (15, 25)
        self.mock_root.winfo_x.return_value = 100
        self.mock_root.winfo_y.return_value = 200

        event_drag = MagicMock(x=15, y=25)
        self.display.drag(event_drag)
        # Expected new x = 100 - 10 + 15 = 105
        # Expected new y = 200 - 20 + 25 = 205
        self.mock_root.geometry.assert_called_with("+105+205")

    def test_drag_bindings(self):
        """ Test that bindings are applied to both root and label """
        # Verify bind was called on both root and label
        self.mock_root.bind.assert_any_call("<Button-1>", self.display.start_drag)
        self.mock_root.bind.assert_any_call("<B1-Motion>", self.display.drag)
        self.mock_label_instance.bind.assert_any_call("<Button-1>", self.display.start_drag)
        self.mock_label_instance.bind.assert_any_call("<B1-Motion>", self.display.drag)

    def test_quit_bindings(self):
        """ Escape and right-click must be bound so the borderless window can be closed """
        root_bindings = [c.args[0] for c in self.mock_root.bind.call_args_list]
        self.assertIn("<Escape>", root_bindings)
        self.assertIn("<Button-2>", root_bindings)
        self.assertIn("<Button-3>", root_bindings)
        self.mock_menu_instance.add_command.assert_called_once_with(
            label="Quit", command=self.mock_root.destroy
        )

    def test_show_menu(self):
        """ Right-click pops the context menu at the pointer """
        event = MagicMock()
        event.x_root = 100
        event.y_root = 200
        self.display.show_menu(event)
        self.mock_menu_instance.tk_popup.assert_called_once_with(100, 200)


if __name__ == '__main__':
    unittest.main()
