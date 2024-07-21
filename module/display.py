### DisplayTranslation class

import tkinter as tk

class DisplayTranslation:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Real-Time Translation")
        self.label = tk.Label(self.root, text="Waiting for translation...", font=("Helvetica", 16), wraplength=500)
        self.label.pack(pady=20, padx=20)

    def update_label(self, new_translation):
        self.label.config(text=new_translation)

    def start_gui(self):
        self.root.mainloop()
