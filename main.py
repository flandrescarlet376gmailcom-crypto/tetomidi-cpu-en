import ctypes
import datetime
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageDraw

from api_client import ApiClient, BridgeClient
from glass import GlassButton
from runtime import resource_path

# Give the app its own taskbar identity on Windows
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("tetomidi.app")
    except Exception:
        pass

BG = "#000000"
TEXT = "#ffffff"
MUTED = "#8a8a8a"
W = 404  # content width
DISCORD_URL = "https://discord.gg/peaqm6uqgB"
AUDIO_TYPES = "*.mp3 *.mp4 *.m4a *.wav *.flac *.ogg *.aac *.mkv *.webm"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_CONFIG = {"mode": "server", "server": "http://127.0.0.1:8765", "token": "",
                  "file_path": "/transcribe", "link_path": "/transcribe-url"}

GUIDE_TEXT = (
    "How to use tetomidi\n\n"
    "1. Choose a file: click \"Select audio / video file\" (mp3, mp4, m4a, wav and more).\n\n"
    "2. Or paste a SoundCloud link into the box. The server downloads the audio.\n\n"
    "3. Click \"Transcribe\". The file is sent to the server and converted to MIDI.\n\n"
    "4. Wait until the status shows Done. Click the \u2715 button to stop early.\n\n"
    "5. Click the folder icon to open the MIDI file, or \"Back\" to convert another file.\n\n"
    "MIDI files are saved in the midi folder next to the app. "
    "Only use audio you have the right to convert."
)


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


def _log(msg):
    """Append a line to tetomidi.log next to the app, so problems leave a trace."""
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(_app_dir(), "tetomidi.log"), "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    _log("Unhandled error:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))


sys.excepthook = _excepthook


def load_config():
    """Read tetomidi.json next to the app. Create it with defaults on first run."""
    path = os.path.join(_app_dir(), "tetomidi.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, encoding="utf-8") as f:
            cfg = dict(DEFAULT_CONFIG)
            cfg.update(json.load(f))
        return cfg
    except Exception:
        _log("Could not read tetomidi.json, using defaults")
        return dict(DEFAULT_CONFIG)


def make_client(cfg):
    """'bridge' sends files and links to an existing endpoint; 'server' uses our own server.py."""
    if cfg.get("mode") == "bridge":
        return BridgeClient(cfg["server"], cfg.get("file_path", "/transcribe"),
                            cfg.get("link_path", "/transcribe-url"), cfg.get("token", ""))
    return ApiClient(cfg["server"], cfg.get("token", ""))


def output_dir():
    """'midi' folder next to the app; fall back to Documents if not writable."""
    d = os.path.join(_app_dir(), "midi")
    try:
        os.makedirs(d, exist_ok=True)
        if not os.access(d, os.W_OK):
            raise OSError
    except OSError:
        d = os.path.join(os.path.expanduser("~"), "Documents", "tetomidi", "midi")
        os.makedirs(d, exist_ok=True)
    return d


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path = os.path.join(folder, name)
    i = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path


def _folder_icon(size=26):
    """Draw a simple yellow folder icon (no external asset needed)."""
    from PIL import ImageDraw as _D
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = _D.Draw(img)
    gold = "#E8C15A"
    d.rounded_rectangle((S * 0.08, S * 0.18, S * 0.42, S * 0.36), radius=S * 0.05, fill=gold)
    d.rounded_rectangle((S * 0.08, S * 0.30, S * 0.92, S * 0.82), radius=S * 0.08, fill=gold)
    return img.resize((size, size), Image.LANCZOS)


def _discord_icon(size=26):
    """Simple Discord-style icon used only if assets/discord.png is missing."""
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((S * 0.08, S * 0.18, S * 0.92, S * 0.82), radius=S * 0.22, fill="#5865F2")
    d.ellipse((S * 0.30, S * 0.38, S * 0.46, S * 0.58), fill="#ffffff")
    d.ellipse((S * 0.54, S * 0.38, S * 0.70, S * 0.58), fill="#ffffff")
    return img.resize((size, size), Image.LANCZOS)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("tetomidi")
        self.geometry("460x800")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        ico = resource_path("assets/tetomidi.ico")
        if os.path.exists(ico):
            self.after(250, lambda: self.iconbitmap(ico))

        self.cfg = load_config()
        self.api = make_client(self.cfg)
        self.src = None
        self.job_id = None
        self.t0 = None
        self._hb = 0
        self._submitting = False
        self._poll_busy = False
        self.folder = None
        self.last_mid = None
        self.logs = []
        self._log_box = None
        self._log_win = None
        self._guide = None

        self._build()
        self._check_server()

        # Intro splash: hide the main window, show splash, then reveal the app
        self.withdraw()
        self._show_intro()

    # ---------- intro ----------
    def _show_intro(self):
        splash = ctk.CTkToplevel(self)
        splash.overrideredirect(True)
        splash.configure(fg_color=BG)
        w, h = 380, 330
        x = (splash.winfo_screenwidth() - w) // 2
        y = (splash.winfo_screenheight() - h) // 2
        splash.geometry(f"{w}x{h}+{x}+{y}")
        splash.attributes("-topmost", True)
        splash.attributes("-alpha", 0.0)

        frame = ctk.CTkFrame(splash, fg_color=BG)
        frame.pack(expand=True, fill="both", padx=24, pady=24)

        logo_path = resource_path("assets/logo.png")
        if os.path.exists(logo_path):
            splash._logo = ctk.CTkImage(Image.open(logo_path), size=(110, 110))
            ctk.CTkLabel(frame, image=splash._logo, text="").pack(pady=(14, 10))

        title = ctk.CTkLabel(frame, text="", text_color=TEXT,
                             font=ctk.CTkFont(size=30, weight="bold"))
        title.pack()
        ctk.CTkLabel(frame, text="Transcriber MIDI", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(pady=(2, 18))

        bar = ctk.CTkProgressBar(frame, width=240, height=4,
                                 fg_color="#151515", progress_color=TEXT)
        bar.set(0)
        bar.pack()
        status = ctk.CTkLabel(frame, text="Starting", text_color=MUTED,
                              font=ctk.CTkFont(size=11))
        status.pack(pady=(10, 0))

        word = "tetomidi"
        total_ms, tick_ms, fade_ms = 2800, 30, 450
        splash._t = 0

        def step():
            t = splash._t
            if t < fade_ms:
                alpha = t / fade_ms
            elif t > total_ms - fade_ms:
                alpha = (total_ms - t) / fade_ms
            else:
                alpha = 1.0
            n = min(len(word), int(len(word) * min(1.0, t / (total_ms * 0.6))) + 1)
            try:
                splash.attributes("-alpha", max(0.0, min(1.0, alpha)))
                title.configure(text=word[:n])
                bar.set(min(1.0, t / total_ms))
                if t > total_ms * 0.5:
                    status.configure(text="Loading")
            except Exception:
                return
            splash._t += tick_ms
            if t >= total_ms:
                self._finish_intro(splash)
            else:
                splash.after(tick_ms, step)

        step()

    def _finish_intro(self, splash):
        try:
            splash.destroy()
        except Exception:
            pass
        self.deiconify()
        self.lift()
        self.focus_force()

    # ---------- background work ----------
    def _bg(self, fn, on_ok, on_err=None):
        """Run a network call in a thread and deliver the result on the UI thread."""
        q = queue.Queue()

        def run():
            try:
                q.put(("ok", fn()))
            except Exception as e:
                q.put(("err", str(e)))

        threading.Thread(target=run, daemon=True).start()

        def check():
            try:
                kind, val = q.get_nowait()
            except queue.Empty:
                self.after(100, check)
                return
            if kind == "ok":
                on_ok(val)
            elif on_err:
                on_err(val)
            else:
                self._ui_log("Error: " + val)

        self.after(100, check)

    def _check_server(self):
        host = self.cfg["server"]
        self.server_lbl.configure(text="Server: checking")
        self._bg(lambda: self.api.health(),
                 lambda _: self.server_lbl.configure(text=f"Server: online  {host}", text_color=TEXT),
                 lambda m: self.server_lbl.configure(
                     text=f"Server offline. Check tetomidi.json ({m[:60]})", text_color=MUTED))

    # ---------- layout ----------
    def _build(self):
        wrap = ctk.CTkFrame(self, fg_color=BG)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # Footer first, so it always keeps its space at the bottom
        footer = ctk.CTkFrame(wrap, fg_color=BG)
        footer.pack(side="bottom", pady=(14, 0))
        folder_small = ctk.CTkImage(light_image=_folder_icon(), dark_image=_folder_icon(),
                                    size=(24, 24))
        ctk.CTkButton(footer, text="", image=folder_small, width=40, height=40,
                      corner_radius=20, fg_color="#151515", hover_color="#262626",
                      command=self.open_result).pack(side="left", padx=8)
        ctk.CTkButton(footer, text="?", width=40, height=40, corner_radius=20,
                      fg_color="#151515", hover_color="#262626", text_color=TEXT,
                      font=ctk.CTkFont(size=16, weight="bold"),
                      command=self.show_guide).pack(side="left", padx=8)
        discord_path = resource_path("assets/discord.png")
        if os.path.exists(discord_path):
            discord_pil = Image.open(discord_path).convert("RGBA")
        else:
            discord_pil = _discord_icon()
        discord_img = ctk.CTkImage(light_image=discord_pil, dark_image=discord_pil, size=(30, 30))
        ctk.CTkButton(footer, text="", image=discord_img, width=40, height=40,
                      corner_radius=20, fg_color="#151515", hover_color="#262626",
                      command=lambda: webbrowser.open(DISCORD_URL)).pack(side="left", padx=8)
        ctk.CTkButton(footer, text="LOG", width=40, height=40, corner_radius=8,
                      fg_color="#151515", hover_color="#262626", text_color=TEXT,
                      font=ctk.CTkFont(size=10, weight="bold"),
                      command=self.show_log).pack(side="left", padx=8)

        # Header
        logo_path = resource_path("assets/logo.png")
        if os.path.exists(logo_path):
            logo = ctk.CTkImage(Image.open(logo_path), size=(96, 96))
            ctk.CTkLabel(wrap, image=logo, text="").pack(pady=(8, 4))
        ctk.CTkLabel(wrap, text="tetomidi", text_color=TEXT,
                     font=ctk.CTkFont(size=26, weight="bold")).pack()
        ctk.CTkLabel(wrap, text="Transcriber MIDI", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(pady=(0, 22))

        # File picker
        GlassButton(wrap, "Select audio / video file", W, 48, command=self.pick_file,
                    font=ctk.CTkFont(size=14)).pack()
        self.file_lbl = ctk.CTkLabel(wrap, text="No file selected", text_color=MUTED,
                                     font=ctk.CTkFont(size=12), wraplength=380)
        self.file_lbl.pack(pady=(8, 10))

        # Link box
        self.link_entry = ctk.CTkEntry(
            wrap, width=W, height=44, corner_radius=22,
            fg_color="#151515", border_color="#2a2a2a", text_color=TEXT,
            placeholder_text="Paste a SoundCloud or other link", placeholder_text_color=MUTED)
        self.link_entry.pack()

        self.server_lbl = ctk.CTkLabel(wrap, text="", text_color=MUTED,
                                       font=ctk.CTkFont(size=11), wraplength=380)
        self.server_lbl.pack(pady=(10, 14))

        # Run / cancel / result row
        self.row = ctk.CTkFrame(wrap, fg_color=BG, width=W, height=56)
        self.row.pack()
        self.row.pack_propagate(False)

        self.go_btn = GlassButton(self.row, "Transcribe", W, 56, command=self.start,
                                  boost=1.7, font=ctk.CTkFont(size=16, weight="bold"))
        self.go_btn.pack()
        self.busy_btn = GlassButton(self.row, "Processing", W - 66, 56, interactive=False,
                                    boost=1.7, font=ctk.CTkFont(size=16, weight="bold"))
        self.cancel_btn = GlassButton(self.row, "\u2715", 56, 56, command=self.cancel,
                                      font=ctk.CTkFont(size=16))
        folder_img = ctk.CTkImage(light_image=_folder_icon(), dark_image=_folder_icon(),
                                  size=(28, 28))
        self.folder_btn = ctk.CTkButton(self.row, text="", image=folder_img, width=56, height=56,
                                        corner_radius=28, fg_color="#151515",
                                        hover_color="#262626", command=self.open_result)
        self.back_btn = GlassButton(self.row, "Back", W - 66, 56, command=self.reset,
                                    boost=1.7, font=ctk.CTkFont(size=16, weight="bold"))

        self.status = ctk.CTkLabel(wrap, text="", text_color=MUTED,
                                   font=ctk.CTkFont(size=12), wraplength=380)
        self.status.pack(pady=(14, 0))

        self.bar = ctk.CTkProgressBar(wrap, mode="determinate", height=4,
                                      fg_color="#151515", progress_color=TEXT)
        self.bar.set(0)

    # ---------- log window ----------
    def _ui_log(self, msg):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        self.logs.append(line)
        _log(msg)
        box = self._log_box
        if box is not None:
            try:
                box.configure(state="normal")
                box.insert("end", line + "\n")
                box.see("end")
                box.configure(state="disabled")
            except Exception:
                self._log_box = None

    def show_log(self):
        if self._log_win is not None:
            try:
                self._log_win.lift()
                return
            except Exception:
                self._log_win = None
        win = ctk.CTkToplevel(self)
        win.title("Log")
        win.geometry("420x320")
        win.configure(fg_color=BG)
        win.transient(self)
        box = ctk.CTkTextbox(win, width=380, height=260, fg_color="#0d0d0d",
                             text_color=TEXT, font=ctk.CTkFont(family="Consolas", size=12))
        box.pack(padx=16, pady=16, fill="both", expand=True)
        box.insert("end", "\n".join(self.logs) + ("\n" if self.logs else ""))
        box.configure(state="disabled")

        def close():
            self._log_box = None
            self._log_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", close)
        self._log_win = win
        self._log_box = box

    def show_guide(self):
        if self._guide is not None:
            try:
                self._guide.lift()
                return
            except Exception:
                self._guide = None
        g = ctk.CTkToplevel(self)
        g.title("How to use")
        g.geometry("420x440")
        g.resizable(False, False)
        g.configure(fg_color=BG)
        g.transient(self)
        self._guide = g
        ctk.CTkLabel(g, text=GUIDE_TEXT, text_color=TEXT, justify="left", anchor="w",
                     wraplength=370, font=ctk.CTkFont(size=13)).pack(
            fill="both", expand=True, padx=24, pady=(24, 12))
        ctk.CTkButton(g, text="Close", width=140, height=36, fg_color="#151515",
                      hover_color="#262626", command=g.destroy).pack(pady=(0, 20))

    # ---------- actions ----------
    def pick_file(self):
        p = filedialog.askopenfilename(
            filetypes=[("Audio / Video", AUDIO_TYPES), ("All files", "*.*")])
        if p:
            self.src = p
            self.link_entry.delete(0, "end")
            self.file_lbl.configure(text=os.path.basename(p), text_color=TEXT)
            self.status.configure(text="")

    def _show_running_ui(self):
        self.go_btn.pack_forget()
        self.folder_btn.pack_forget()
        self.back_btn.pack_forget()
        self.busy_btn.pack(side="left")
        self.cancel_btn.pack(side="left", padx=(10, 0))
        self.bar.set(0)
        self.bar.pack(fill="x", pady=(18, 0), before=self.status)
        self.status.configure(text="Sending to server")

    def start(self):
        if self.job_id or self._submitting:
            return
        link = self.link_entry.get().strip()
        if not link and not self.src:
            self.status.configure(text="Select a file or paste a link first.")
            return
        if self.cfg.get("mode") != "bridge" and not self.cfg.get("token"):
            self.status.configure(text="Set your token in tetomidi.json first.")
            return
        self._submitting = True
        self._show_running_ui()
        if link:
            label = link
            fn = lambda: self.api.submit_link(link)
        else:
            label = os.path.basename(self.src)
            fn = lambda: self.api.submit_file(self.src)
        self._ui_log(f"Sending: {label}")

        def ok(jid):
            self._submitting = False
            self._begin_job(jid)

        def err(msg):
            self._submitting = False
            self.finish("Error: " + msg)

        self._bg(fn, ok, err)

    def _begin_job(self, jid):
        self.job_id = jid
        self.t0 = time.time()
        self._hb = 0
        self._ui_log(f"Job started on server: {jid[:8]}")
        self.after(800, self._poll)

    def _poll(self):
        if not self.job_id or self._poll_busy:
            return
        self._poll_busy = True
        jid = self.job_id

        def ok(st):
            self._poll_busy = False
            self._apply(st)

        def err(msg):
            self._poll_busy = False
            self.finish("Lost connection to server: " + msg)

        self._bg(lambda: self.api.status(jid), ok, err)

    def _apply(self, st):
        if not self.job_id:
            return  # cancelled or finished in the meantime
        state = st.get("state")
        elapsed = time.time() - self.t0
        minutes = int(elapsed // 60)
        if state == "queued":
            self.status.configure(text=f"Waiting in server queue, position {st.get('position', 0)}")
            self.after(1000, self._poll)
        elif state == "running":
            p = st.get("progress")
            if p is not None:
                self.bar.set(p)
                self.status.configure(text=f"Transcribing to MIDI: ~{int(p * 100)}%")
            else:
                self.status.configure(
                    text=f"Transcribing to MIDI: {minutes} min {int(elapsed % 60)} s")
            if minutes > self._hb:
                self._hb = minutes
                self._ui_log(f"Still working, {minutes} min elapsed")
            self.after(1000, self._poll)
        elif state == "done":
            self._download(st)
        elif state == "error":
            self.finish("Error: " + (st.get("error") or "unknown").strip()[-300:])
        elif state == "cancelled":
            self.finish("Cancelled.")

    def _download(self, st):
        jid = self.job_id
        name = st.get("name") or "result.mid"
        dst = unique_path(output_dir(), name)
        self.status.configure(text="Downloading MIDI")

        def ok(_):
            self.finish(f"Done: {os.path.basename(dst)}", os.path.dirname(dst), dst)

        def err(msg):
            self.finish("Error downloading MIDI: " + msg)

        self._bg(lambda: self.api.download_midi(jid, dst), ok, err)

    def cancel(self):
        if not self.job_id:
            return
        jid = self.job_id
        self._bg(lambda: self.api.cancel(jid),
                 lambda _: self.finish("Cancelled."),
                 lambda m: self.finish("Cancel failed: " + m))

    def finish(self, text, folder=None, mid=None):
        self.job_id = None
        self.bar.set(1.0 if mid else 0)
        self.bar.pack_forget()
        self.busy_btn.pack_forget()
        self.cancel_btn.pack_forget()
        self._ui_log(text.replace("\n", " "))
        self.status.configure(text=text)
        if mid:
            self.folder = folder
            self.last_mid = mid
            self.go_btn.pack_forget()
            self.folder_btn.pack(side="left")
            self.back_btn.pack(side="left", padx=(10, 0))
        else:
            self.go_btn.pack()

    def open_result(self):
        """Open Explorer with the converted file selected, or the midi folder."""
        if self.last_mid and os.path.exists(self.last_mid):
            subprocess.Popen(f'explorer /select,"{os.path.normpath(self.last_mid)}"')
        else:
            os.startfile(output_dir())

    def reset(self):
        """Back to the start state so a new file or link can be sent."""
        self.src = None
        self.last_mid = None
        self.link_entry.delete(0, "end")
        self.file_lbl.configure(text="No file selected", text_color=MUTED)
        self.status.configure(text="")
        self.folder_btn.pack_forget()
        self.back_btn.pack_forget()
        self.go_btn.pack()


if __name__ == "__main__":
    App().mainloop()
