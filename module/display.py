""" This module contains the DisplayTranslation class
which is responsible for displaying the real-time translation on the GUI. """

import tkinter as tk

class DisplayTranslation:
    """ This class is responsible for displaying the real-time translation on the GUI. """
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Real-Time Translation")
        self.root.wm_attributes("-topmost", True)
        self.root.attributes("-alpha", 0.8)

        self.label = tk.Label(self.root,
                              text="Waiting for translation...",
                              font=("Helvetica", 16),
                              wraplength=500)
        self.label.pack(pady=20, padx=20)

    def update_label(self, new_translation):
        """ Updates the label with the new translation. """
        self.label.config(text=new_translation)

    def start_gui(self):
        """ Starts the Tkinter GUI loop. """
        self.root.mainloop()
