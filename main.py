import os
import sys
import queue
import webbrowser
import subprocess
from fast_runtime import thread_count
import datetime
import time
import traceback as _tb

try:
    import psutil
except ImportError:
    psutil = None


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


def _log(msg):
    """Append a line to tetomidi.log next to the app, so crashes leave a trace."""
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(_app_dir(), "tetomidi.log"), "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except Exception:
        pass


# Rough estimate of seconds of processing per second of audio. Tune on your machine.
TIME_PER_SEC = 1.0
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _duration(path):
    """Audio/video length in seconds via ffprobe (bundled with the app). None if unknown."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            creationflags=NO_WINDOW, text=True, timeout=20)
        return float(out.strip())
    except Exception:
        return None


def _excepthook(exc_type, exc, tb):
    _log("Unhandled error:\n" + "".join(_tb.format_exception(exc_type, exc, tb)))


sys.excepthook = _excepthook
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
DISCORD_URL = "https://discord.gg/dbxUt4kBZ"
# "auto" = use all physical CPU cores, or set a number such as 4
THREADS = "auto"

GUIDE_TEXT = (
    "Cách sử dụng tetomidi\n\n"
    "1. Bấm \"Select audio / video file\" và chọn file mp3, mp4, m4a hoặc wav.\n\n"
    "2. Bấm \"Transcribe\" để bắt đầu chuyển sang MIDI.\n\n"
    "3. Chờ đến khi có thông báo hoàn tất. Muốn dừng giữa chừng, bấm nút ✕.\n\n"
    "4. Bấm \"Open midi folder\" để mở thư mục chứa file .mid.\n\n"
    "File MIDI được lưu trong thư mục midi nằm cạnh app. "
    "File dài hoặc máy yếu sẽ mất nhiều thời gian hơn."
)


def _folder_icon(size=26):
    """Draw a simple yellow folder icon (no external asset needed)."""
    from PIL import ImageDraw
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    gold = "#E8C15A"
    d.rounded_rectangle((S * 0.08, S * 0.18, S * 0.42, S * 0.36), radius=S * 0.05, fill=gold)
    d.rounded_rectangle((S * 0.08, S * 0.30, S * 0.92, S * 0.82), radius=S * 0.08, fill=gold)
    return img.resize((size, size), Image.LANCZOS)


def _discord_icon(size=26):
    """Draw a simple Discord-style controller icon (no external asset needed)."""
    from PIL import ImageDraw
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((S * 0.08, S * 0.18, S * 0.92, S * 0.82),
                        radius=S * 0.22, fill="#5865F2")
    d.ellipse((S * 0.30, S * 0.38, S * 0.46, S * 0.58), fill="#ffffff")
    d.ellipse((S * 0.54, S * 0.38, S * 0.70, S * 0.58), fill="#ffffff")
    return img.resize((size, size), Image.LANCZOS)


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


def _tune_cpu():
    """Use the machine's cores efficiently; works on weak/integrated CPUs too."""
    threads = thread_count(os.environ.get("TETOMIDI_THREADS", THREADS))
    os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(threads))
    try:
        import torch
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass  # already set by another call; harmless
    except ImportError:
        pass


def _worker(src, dst, q):
    """Run transcription in a separate process so it can be cancelled."""
    try:
        _tune_cpu()
        _log(f"Worker start, threads={os.environ.get('TETOMIDI_THREADS', THREADS)}")
        sys.argv = ["transkun", src, dst, "--device", "cpu"]
        from transkun import transcribe
        try:
            import torch
            with torch.inference_mode():
                transcribe.main()
        except SystemExit as e:
            if e.code not in (None, 0):
                raise RuntimeError(f"Transkun exited with code {e.code}")
        q.put(("done", dst))
    except Exception:
        _log("Worker error:\n" + traceback.format_exc())
        q.put(("error", traceback.format_exc()))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("tetomidi")
        self.geometry("460x800")
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
        self.last_mid = None
        self.logs = []
        self.duration = None
        self.t0 = None
        self._hb = 0
        self._log_box = None
        self._log_win = None

        self._build()

        # Intro splash: hide the main window, show splash, then reveal the app
        self.withdraw()
        self._show_intro()

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

        ctk.CTkLabel(frame, text="tetomidi", text_color=TEXT,
                     font=ctk.CTkFont(size=30, weight="bold")).pack()
        ctk.CTkLabel(frame, text="Audio → MIDI", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(pady=(2, 18))

        bar = ctk.CTkProgressBar(frame, width=240, height=4,
                                 fg_color="#151515", progress_color=TEXT)
        bar.set(0)
        bar.pack()
        ctk.CTkLabel(frame, text="Đang khởi động", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(pady=(10, 0))

        total_ms, tick_ms, fade_ms = 2600, 30, 400
        splash._t = 0

        def step():
            t = splash._t
            if t < fade_ms:
                alpha = t / fade_ms
            elif t > total_ms - fade_ms:
                alpha = (total_ms - t) / fade_ms
            else:
                alpha = 1.0
            try:
                splash.attributes("-alpha", max(0.0, min(1.0, alpha)))
                bar.set(min(1.0, t / total_ms))
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

    def _build(self):
        wrap = ctk.CTkFrame(self, fg_color=BG)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # Footer: guide + Discord icons (Discord link is hidden behind the icon)
        footer = ctk.CTkFrame(wrap, fg_color=BG)
        footer.pack(side="bottom", pady=(14, 0))
        folder_small = ctk.CTkImage(light_image=_folder_icon(), dark_image=_folder_icon(),
                                    size=(24, 24))
        ctk.CTkButton(
            footer, text="", image=folder_small, width=40, height=40, corner_radius=20,
            fg_color="#151515", hover_color="#262626",
            command=self.open_result).pack(side="left", padx=8)
        ctk.CTkButton(
            footer, text="?", width=40, height=40, corner_radius=20,
            fg_color="#151515", hover_color="#262626", text_color=TEXT,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.show_guide).pack(side="left", padx=8)
        discord_path = resource_path("assets/discord.png")
        if os.path.exists(discord_path):
            discord_pil = Image.open(discord_path).convert("RGBA")
        else:
            discord_pil = _discord_icon()
        discord_img = ctk.CTkImage(light_image=discord_pil,
                                   dark_image=discord_pil, size=(30, 30))
        ctk.CTkButton(
            footer, text="", image=discord_img, width=40, height=40,
            corner_radius=20, fg_color="#151515", hover_color="#262626",
            command=lambda: webbrowser.open(DISCORD_URL)).pack(side="left", padx=8)
        ctk.CTkButton(
            footer, text="LOG", width=40, height=40, corner_radius=8,
            fg_color="#151515", hover_color="#262626", text_color=TEXT,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.show_log).pack(side="left", padx=8)

        logo_path = resource_path("assets/logo.png")
        if os.path.exists(logo_path):
            logo = ctk.CTkImage(Image.open(logo_path), size=(96, 96))
            ctk.CTkLabel(wrap, image=logo, text="").pack(pady=(8, 4))

        ctk.CTkLabel(wrap, text="tetomidi", text_color=TEXT,
                     font=ctk.CTkFont(size=26, weight="bold")).pack()
        ctk.CTkLabel(wrap, text="Audio → MIDI", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(pady=(0, 22))

        # File picker
        GlassButton(wrap, "Select audio / video file", W, 48, command=self.pick_file,
                    font=ctk.CTkFont(size=14)).pack()
        self.file_lbl = ctk.CTkLabel(
            wrap, text="No file selected", text_color=MUTED,
            font=ctk.CTkFont(size=12), wraplength=380)
        self.file_lbl.pack(pady=(8, 16))

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
            wrap, mode="determinate", height=4,
            fg_color="#151515", progress_color=TEXT)

        # Shown after a finished transcription, inside the same row
        folder_img = ctk.CTkImage(light_image=_folder_icon(), dark_image=_folder_icon(),
                                  size=(28, 28))
        self.folder_btn = ctk.CTkButton(
            self.row, text="", image=folder_img, width=56, height=56,
            corner_radius=28, fg_color="#151515", hover_color="#262626",
            command=self.open_result)
        self.back_btn = GlassButton(
            self.row, "Quay lại", W - 66, 56, command=self.reset,
            boost=1.7, font=ctk.CTkFont(size=16, weight="bold"))

    # ---------- log window ----------
    def _ui_log(self, msg):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        self.logs.append(line)
        _log(msg)
        box = getattr(self, "_log_box", None)
        if box is not None:
            try:
                box.configure(state="normal")
                box.insert("end", line + "\n")
                box.see("end")
                box.configure(state="disabled")
            except Exception:
                self._log_box = None

    def show_log(self):
        if getattr(self, "_log_win", None) is not None:
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
        if getattr(self, "_guide", None) and self._guide.winfo_exists():
            self._guide.lift()
            return
        g = ctk.CTkToplevel(self)
        g.title("Hướng dẫn sử dụng")
        g.geometry("400x400")
        g.resizable(False, False)
        g.configure(fg_color=BG)
        g.transient(self)
        self._guide = g
        ctk.CTkLabel(g, text=GUIDE_TEXT, text_color=TEXT, justify="left",
                     anchor="w", wraplength=350,
                     font=ctk.CTkFont(size=13)).pack(
            fill="both", expand=True, padx=24, pady=(24, 12))
        ctk.CTkButton(g, text="Đóng", width=140, height=36, fg_color="#151515",
                      hover_color="#262626", command=g.destroy).pack(pady=(0, 20))

    # ---------- actions ----------
    def pick_file(self):
        p = filedialog.askopenfilename(
            filetypes=[("Audio / Video",
                        "*.mp3 *.mp4 *.m4a *.wav *.flac *.ogg *.aac *.mkv *.webm"),
                       ("All files", "*.*")])
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
        os.environ.pop("TETOMIDI_THREADS", None)
        if psutil is not None:
            avail_gb = psutil.virtual_memory().available / (1024 ** 3)
            if avail_gb < 3:
                os.environ["TETOMIDI_THREADS"] = "2"
                _log(f"Low RAM ({avail_gb:.1f} GB free): using 2 threads")
        self.duration = _duration(self.src)
        self.t0 = time.time()
        self._hb = 0
        self.bar.set(0)
        if self.duration:
            self._ui_log(f"Bắt đầu: {os.path.basename(self.src)}, dài {self.duration:.0f} giây")
        else:
            self._ui_log(f"Bắt đầu: {os.path.basename(self.src)} (không đọc được độ dài)")

        self.q = mp.Queue()
        self.proc = mp.Process(target=_worker,
                               args=(self.src, dst, self.q), daemon=True)
        self.proc.start()

        self.go_btn.pack_forget()
        self.busy_btn.pack(side="left")
        self.cancel_btn.pack(side="left", padx=(10, 0))
        self.bar.pack(fill="x", pady=(18, 0), before=self.status)
        self.status.configure(text="Đang chuyển sang MIDI: 0%")
        self.after(300, self.poll)

    def _tick(self):
        """Estimated progress from elapsed time and audio length (Transkun has no progress hook)."""
        if self.t0 is None:
            return
        elapsed = time.time() - self.t0
        minutes = int(elapsed // 60)
        if minutes > self._hb:
            self._hb = minutes
            self._ui_log(f"Vẫn đang chuyển đổi, đã chạy {minutes} phút")
        if self.duration:
            est = max(5.0, self.duration * TIME_PER_SEC)
            if elapsed < est:
                pct = min(95.0, elapsed / est * 100)
                self.bar.set(pct / 100)
                self.status.configure(text=f"Đang chuyển sang MIDI: ~{pct:.0f}%")
            else:
                self.status.configure(
                    text=f"Đang chuyển sang MIDI: đã {minutes} phút, file dài nên còn lâu")
        else:
            self.status.configure(text=f"Đang chuyển sang MIDI: {minutes} phút {int(elapsed % 60)} giây")

    def poll(self):
        if self.proc is None:
            return
        self._tick()
        try:
            kind, msg = self.q.get_nowait()
        except queue.Empty:
            if self.proc.is_alive():
                self.after(300, self.poll)
            else:
                code = self.proc.exitcode
                _log(f"Worker stopped without result, exit code {code}")
                hint = " (có thể hết RAM)" if code not in (0, None) else ""
                self.finish(f"Dừng bất thường, mã {code}{hint}. Xem tetomidi.log.")
            return
        if kind == "done":
            self.finish(f"Done: {os.path.basename(msg)}",
                        os.path.dirname(msg), msg)
        else:
            self.finish("Error:\n" + msg[-400:])

    def cancel(self):
        if self.proc and self.proc.is_alive():
            self.proc.terminate()
        self.finish("Cancelled.")

    def finish(self, text, folder=None, mid=None):
        self.proc = None
        self.bar.set(1.0 if mid else 0)
        self.bar.pack_forget()
        self._ui_log(text.replace("\n", " "))
        self.t0 = None
        self.busy_btn.pack_forget()
        self.cancel_btn.pack_forget()
        self.status.configure(text=text)
        if mid:
            # Finished: show folder icon (left) and back button (right)
            self.folder = folder
            self.last_mid = mid
            self.go_btn.pack_forget()
            self.folder_btn.pack(side="left")
            self.back_btn.pack(side="left", padx=(10, 0))
        else:
            self.go_btn.pack()

    def open_result(self):
        """Open Explorer in the midi folder with the converted file selected."""
        if self.last_mid and os.path.exists(self.last_mid):
            subprocess.Popen(f'explorer /select,"{os.path.normpath(self.last_mid)}"')
        elif self.folder:
            os.startfile(self.folder)
        else:
            os.startfile(output_dir())

    def reset(self):
        """Go back to the start state so a new file can be converted."""
        self.src = None
        self.last_mid = None
        self.file_lbl.configure(text="No file selected", text_color=MUTED)
        self.status.configure(text="")
        self.folder_btn.pack_forget()
        self.back_btn.pack_forget()
        self.go_btn.pack()


if __name__ == "__main__":
    mp.freeze_support()
    App().mainloop()
