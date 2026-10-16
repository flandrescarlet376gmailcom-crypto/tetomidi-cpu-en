import os
import sys
import queue
import traceback
import multiprocessing as mp
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

from runtime import setup_ffmpeg, resource_path
from glass import GlassButton

setup_ffmpeg()

# Give the app its own taskbar identity on Windows
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "tetomidi.app")
    except Exception:
        pass

BG = "#000000"
TEXT = "#ffffff"
MUTED = "#8a8a8a"
W = 404  # content width


def output_dir():
    """'midi' folder next to the exe; fall back to Documents if not writable."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath(".")
    d = os.path.join(base, "midi")
    try:
        os.makedirs(d, exist_ok=True)
        if not os.access(d, os.W_OK):
            raise OSError
    except OSError:
        d = os.path.join(os.path.expanduser("~"), "Documents", "tetomidi", "midi")
        os.makedirs(d, exist_ok=True)
    return d


def _worker(src, dst, q):
    """Run transcription in a separate process so it can be cancelled."""
    try:
        sys.argv = ["transkun", src, dst, "--device", "cpu"]
        from transkun import transcribe
        try:
            transcribe.main()
        except SystemExit as e:
            if e.code not in (None, 0):
                raise RuntimeError(f"Transkun exited with code {e.code}")
        q.put(("done", dst))
    except Exception:
        q.put(("error", traceback.format_exc()))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("tetomidi")
        self.geometry("460x740")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        # Window icon (delayed because customtkinter sets a default icon after open)
        ico = resource_path("assets/tetomidi.ico")
        if os.path.exists(ico):
            self.after(250, lambda: self.iconbitmap(ico))

        self.src = None
        self.proc = None
        self.q = None
        self.folder = None

        self._build()

    def _build(self):
        wrap = ctk.CTkFrame(self, fg_color=BG)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        logo_path = resource_path("assets/logo.png")
        if os.path.exists(logo_path):
            logo = ctk.CTkImage(Image.open(logo_path), size=(96, 96))
            ctk.CTkLabel(wrap, image=logo, text="").pack(pady=(8, 4))

        ctk.CTkLabel(wrap, text="tetomidi", text_color=TEXT,
                     font=ctk.CTkFont(size=26, weight="bold")).pack()
        ctk.CTkLabel(wrap, text="MP3 → MIDI", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(pady=(0, 22))

        # File picker
        GlassButton(wrap, "Select MP3 file", W, 48, command=self.pick_file,
                    font=ctk.CTkFont(size=14)).pack()
        self.file_lbl = ctk.CTkLabel(
            wrap, text="No file selected", text_color=MUTED,
            font=ctk.CTkFont(size=12), wraplength=380)
        self.file_lbl.pack(pady=(8, 16))

        # Model
        ctk.CTkLabel(wrap, text="Model", text_color=MUTED, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(fill="x")
        GlassButton(wrap, "Transkun V2", W, 44, interactive=False,
                    font=ctk.CTkFont(size=13)).pack(pady=(4, 14))

        # Device
        ctk.CTkLabel(wrap, text="Device", text_color=MUTED, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(fill="x")
        GlassButton(wrap, "CPU", W, 44, interactive=False,
                    font=ctk.CTkFont(size=13)).pack(pady=(4, 20))

        # Run / Cancel row
        self.row = ctk.CTkFrame(wrap, fg_color=BG, width=W, height=56)
        self.row.pack()
        self.row.pack_propagate(False)

        self.go_btn = GlassButton(
            self.row, "Transcribe", W, 56, command=self.start, boost=1.7,
            font=ctk.CTkFont(size=16, weight="bold"))
        self.go_btn.pack()

        self.busy_btn = GlassButton(
            self.row, "Processing…", W - 66, 56, interactive=False,
            boost=1.7, font=ctk.CTkFont(size=16, weight="bold"))
        self.cancel_btn = GlassButton(
            self.row, "✕", 56, 56, command=self.cancel,
            font=ctk.CTkFont(size=16))

        self.status = ctk.CTkLabel(
            wrap, text="", text_color=MUTED, font=ctk.CTkFont(size=12),
            wraplength=380, justify="center")
        self.status.pack(pady=(18, 0))

        self.bar = ctk.CTkProgressBar(
            wrap, mode="indeterminate", height=4,
            fg_color="#151515", progress_color=TEXT)

        self.open_btn = GlassButton(
            wrap, "Open midi folder", W, 46,
            command=lambda: os.startfile(self.folder),
            font=ctk.CTkFont(size=14))

    # ---------- actions ----------
    def pick_file(self):
        p = filedialog.askopenfilename(
            filetypes=[("Audio", "*.mp3 *.wav *.flac *.m4a *.ogg")])
        if p:
            self.src = p
            self.file_lbl.configure(text=os.path.basename(p), text_color=TEXT)
            self.status.configure(text="")

    def start(self):
        if not self.src:
            self.status.configure(text="Please select a file first.")
            return
        name = os.path.splitext(os.path.basename(self.src))[0] + ".mid"
        dst = os.path.join(output_dir(), name)
        self.open_btn.pack_forget()

        self.q = mp.Queue()
        self.proc = mp.Process(target=_worker,
                               args=(self.src, dst, self.q), daemon=True)
        self.proc.start()

        self.go_btn.pack_forget()
        self.busy_btn.pack(side="left")
        self.cancel_btn.pack(side="left", padx=(10, 0))
        self.bar.pack(fill="x", pady=(18, 0), before=self.status)
        self.bar.start()
        self.status.configure(text="Converting to MIDI on CPU…")
        self.after(300, self.poll)

    def poll(self):
        if self.proc is None:
            return
        try:
            kind, msg = self.q.get_nowait()
        except queue.Empty:
            if self.proc.is_alive():
                self.after(300, self.poll)
            else:
                self.finish("Process stopped unexpectedly.")
            return
        if kind == "done":
            self.finish(f"Done: {os.path.basename(msg)}",
                        os.path.dirname(msg))
        else:
            self.finish("Error:\n" + msg[-400:])

    def cancel(self):
        if self.proc and self.proc.is_alive():
            self.proc.terminate()
        self.finish("Cancelled.")

    def finish(self, text, folder=None):
        self.proc = None
        self.bar.stop()
        self.bar.pack_forget()
        self.busy_btn.pack_forget()
        self.cancel_btn.pack_forget()
        self.go_btn.pack()
        self.status.configure(text=text)
        if folder:
            self.folder = folder
            self.open_btn.pack(pady=(12, 0))


if __name__ == "__main__":
    mp.freeze_support()
    App().mainloop()
