""" This module contains the DisplayTranslation class
which is responsible for displaying the real-time translation on the GUI. """

import tkinter as tk
import json
import logging

from module.utility.config import load_config

logger = logging.getLogger(__name__)

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
    "draggable": True,
    "grow_up": True  # False: anchor the top edge, so a bar near the top grows downward
}


class DisplayTranslation:
    """ This class is responsible for displaying the real-time translation on the GUI. """
    def __init__(self, config_path="config.json", root=None, config=None):
        self.config_path = config_path
        # Load config with defaults
        self.config = DEFAULT_UI_CONFIG.copy()

        if config is not None:
            self.config.update(config)
        else:
            self.config.update(load_config(config_path).get("ui", {}))

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
        x = self.config.get("window_x")
        y = self.config.get("window_y")
        if x is None or y is None:
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
                widget.bind("<ButtonRelease-1>", self.end_drag)

        self._drag_data = {"x": 0, "y": 0}

        # Quit controls: borderless windows have no close button
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Quit", command=self.root.destroy)
        self.root.bind("<Escape>", lambda event: self.root.destroy())
        for widget in (self.root, self.label):
            widget.bind("<Button-2>", self.show_menu)  # macOS aqua right-click
            widget.bind("<Button-3>", self.show_menu)

    def show_menu(self, event):
        """ Shows the right-click context menu at the pointer. """
        self.menu.tk_popup(event.x_root, event.y_root)

    def start_drag(self, event):
        """ Start dragging the window. """
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def drag(self, event):
        """ Drag the window to a new location. """
        x = self.root.winfo_x() - self._drag_data["x"] + event.x
        y = self.root.winfo_y() - self._drag_data["y"] + event.y
        self.root.geometry(f"+{x}+{y}")

    def end_drag(self, event):
        """ Persists the dragged window position to the config file. """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("ui", {})["window_x"] = self.root.winfo_x()
            data["ui"]["window_y"] = self.root.winfo_y()
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Could not persist window position: %s", e)

    def update_label(self, text):
        """ Updates the label and resizes the window to fit, anchoring the bottom edge
        (ui.grow_up, default) or the top edge (grow_up false, for a bar at the screen top). """
        self.label.config(text=text)
        self.root.update_idletasks()
        needed = self.label.winfo_reqheight() + 20
        base = self.config["window_height"]
        # ponytail: cap on a share of the screen, not on window_height * 3 - that base is a
        # single-line height for the default font, so a large font_size clipped wrapped lines.
        cap = int(self.root.winfo_screenheight() * 0.4)
        height = max(base, min(needed, cap))
        if height != self.root.winfo_height():
            # top-left origin: shifting y up keeps the bottom edge; leaving y grows downward.
            y = self.root.winfo_y()
            if self.config["grow_up"]:
                y += self.root.winfo_height() - height
            self.root.geometry(f"{self.root.winfo_width()}x{height}+{self.root.winfo_x()}+{y}")

    def start_gui(self):
        """ Starts the Tkinter GUI loop. """
        self.root.mainloop()
