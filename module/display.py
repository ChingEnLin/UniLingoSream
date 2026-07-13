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

    def enable_fullscreen_overlay(self):
        """Enable the window to float over full screen apps on macOS."""
        import platform
        if platform.system() != "Darwin":
            return
            
        # Skip if running inside unit tests with a mock root
        if hasattr(self.root, "__class__") and self.root.__class__.__name__ == "MagicMock":
            return
            
        try:
            self.root.update()
            
            import ctypes
            import ctypes.util
            
            lib_path = ctypes.util.find_library('objc')
            if not lib_path:
                logger.warning("Could not find objc library path.")
                return
                
            objc = ctypes.cdll.LoadLibrary(lib_path)
            
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            objc.objc_getClass.restype = ctypes.c_void_p
            
            objc.sel_registerName.argtypes = [ctypes.c_char_p]
            objc.sel_registerName.restype = ctypes.c_void_p
            OBJC_MSG_SEND = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            OBJC_MSG_SEND_IDX = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong)
            OBJC_MSG_SEND_STR = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)
            OBJC_MSG_SEND_VOID_ULONG = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong)
            OBJC_MSG_SEND_BOOL = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            
            send_std = OBJC_MSG_SEND(objc.objc_msgSend)
            send_idx = OBJC_MSG_SEND_IDX(objc.objc_msgSend)
            send_str = OBJC_MSG_SEND_STR(objc.objc_msgSend)
            send_void_ulong = OBJC_MSG_SEND_VOID_ULONG(objc.objc_msgSend)
            send_bool = OBJC_MSG_SEND_BOOL(objc.objc_msgSend)
            
            sel_sharedApplication = objc.sel_registerName(b"sharedApplication")
            sel_windows = objc.sel_registerName(b"windows")
            sel_count = objc.sel_registerName(b"count")
            sel_objectAtIndex = objc.sel_registerName(b"objectAtIndex:")
            sel_title = objc.sel_registerName(b"title")
            sel_UTF8String = objc.sel_registerName(b"UTF8String")
            sel_setCollectionBehavior = objc.sel_registerName(b"setCollectionBehavior:")
            sel_respondsToSelector = objc.sel_registerName(b"respondsToSelector:")
            
            nsapp_class = objc.objc_getClass(b"NSApplication")
            if not nsapp_class:
                return
                
            nsapp = send_std(nsapp_class, sel_sharedApplication)
            if not nsapp:
                return
                
            windows = send_std(nsapp, sel_windows)
            if not windows:
                return
                
            count = send_std(windows, sel_count)
            target_window = None
            for i in range(count):
                win = send_idx(windows, sel_objectAtIndex, i)
                if not win:
                    continue
                # Safely check if the window object responds to the 'title' selector
                if send_bool(win, sel_respondsToSelector, sel_title):
                    title_nsstring = send_std(win, sel_title)
                    if title_nsstring:
                        # Safely check if the title string responds to the 'UTF8String' selector
                        if send_bool(title_nsstring, sel_respondsToSelector, sel_UTF8String):
                            title_bytes = send_str(title_nsstring, sel_UTF8String)
                            title = title_bytes.decode('utf-8') if title_bytes else ""
                            if "UniLingoStream Subtitles" in title:
                                target_window = win
                                break
            
            if target_window:
                # Safely check if the target window responds to 'setCollectionBehavior:'
                if send_bool(target_window, sel_respondsToSelector, sel_setCollectionBehavior):
                    # NSWindowCollectionBehaviorCanJoinAllSpaces = 1 << 0 (1)
                    # NSWindowCollectionBehaviorFullScreenAuxiliary = 1 << 6 (64)
                    send_void_ulong(target_window, sel_setCollectionBehavior, 65)
                    logger.info("Successfully enabled macOS full screen support for overlay window.")
                else:
                    logger.warning("Target window does not respond to setCollectionBehavior:")
            else:
                logger.warning("Could not find UniLingoStream Subtitles window in NSApplication windows.")
                
        except Exception as e:
            logger.warning("Failed to enable macOS full screen support: %s", e)

    def start_gui(self):
        """ Starts the Tkinter GUI loop. """
        self.enable_fullscreen_overlay()
        self.root.mainloop()
