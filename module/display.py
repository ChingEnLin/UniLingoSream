""" This module contains the DisplayTranslation class
which is responsible for displaying the real-time translation on the GUI. """

import tkinter as tk
import json
import os
import logging

logger = logging.getLogger('root')

DEFAULT_UI_CONFIG = {
    "font_family": "Helvetica",
    "font_size": 24,
    "text_color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 0.6,
    "window_height": 90,
    "window_width_percent": 80,
    "bottom_margin": 100,
    "always_on_top": True,
    "draggable": True
}


class DisplayTranslation:
    """ This class is responsible for displaying the real-time translation on the GUI. """
    def __init__(self, config_path="config.json", root=None, config=None):
        # Load config with defaults
        self.config = DEFAULT_UI_CONFIG.copy()

        if config is not None:
            self.config.update(config)
        else:
            try:
                if os.path.exists(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        file_config = json.load(f)
                        if "ui" in file_config:
                            self.config.update(file_config["ui"])
            except Exception as e:
                logger.error(f"Error loading configuration from {config_path}: {e}. Using default UI settings.")

        if root is None:
            self.root = tk.Tk()
        else:
            self.root = root

        self.root.title("UniLingoStream Subtitles")

        # Borderless overlay
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", self.config["bg_opacity"])
        self.root.wm_attributes("-topmost", self.config["always_on_top"])
        self.root.configure(bg=self.config["bg_color"])

        # Sizing and coordinates
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        width = int(screen_width * self.config["window_width_percent"] / 100)
        height = self.config["window_height"]
        x = (screen_width - width) // 2
        y = screen_height - height - self.config["bottom_margin"]

        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # Subtitle Text Label
        self.label = tk.Label(
            self.root,
            text="Waiting for translation...",
            font=(self.config["font_family"], self.config["font_size"]),
            fg=self.config["text_color"],
            bg=self.config["bg_color"],
            wraplength=width - 40,
            justify="center"
        )
        self.label.pack(expand=True, fill="both", pady=10, padx=20)

        # Draggability binding
        if self.config["draggable"]:
            for widget in (self.root, self.label):
                widget.bind("<Button-1>", self.start_drag)
                widget.bind("<B1-Motion>", self.drag)

        self._drag_data = {"x": 0, "y": 0}

    def start_drag(self, event):
        """ Start dragging the window. """
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def drag(self, event):
        """ Drag the window to a new location. """
        x = self.root.winfo_x() - self._drag_data["x"] + event.x
        y = self.root.winfo_y() - self._drag_data["y"] + event.y
        self.root.geometry(f"+{x}+{y}")

    def update_label(self, text):
        """ Updates the label with the new translation. """
        self.label.config(text=text)

    def start_gui(self):
        """ Starts the Tkinter GUI loop. """
        self.root.mainloop()
