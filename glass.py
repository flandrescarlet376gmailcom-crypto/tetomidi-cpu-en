import customtkinter as ctk
from PIL import Image, ImageDraw, ImageChops

K = 4        # hệ số vẽ (siêu mẫu) để viền mịn
OUT = 2      # mật độ điểm ảnh khi hiển thị

LEVELS = {
    "normal":   dict(top=(255, 255, 255, 64), bot=(170, 190, 255, 26),
                     hi=70, rim_top=170, rim_bot=50),
    "hover":    dict(top=(255, 255, 255, 92), bot=(180, 200, 255, 44),
                     hi=90, rim_top=210, rim_bot=80),
    "press":    dict(top=(255, 255, 255, 36), bot=(150, 170, 255, 16),
                     hi=30, rim_top=120, rim_bot=40),
    "disabled": dict(top=(255, 255, 255, 22), bot=(255, 255, 255, 10),
                     hi=0, rim_top=60, rim_bot=20),
}


def _vgrad(w, h, top, bottom):
    col = Image.new("RGBA", (1, h))
    px = col.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4))
    return col.resize((w, h))


def glass_image(w, h, radius, state="normal", boost=1.0):
    W, H, R = w * K, h * K, radius * K
    p = LEVELS[state]

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), R, fill=255)

    def boosted(c):
        return (c[0], c[1], c[2], min(255, int(c[3] * boost)))

    body = _vgrad(W, H, boosted(p["top"]), boosted(p["bot"]))

    # vệt sáng phản chiếu nửa trên
    if p["hi"] > 0:
        hi_h = int(H * 0.5)
        inset = int(2.5 * K)
        hi = _vgrad(W, hi_h, (255, 255, 255, p["hi"]), (255, 255, 255, 0))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.paste(hi, (0, inset))
        body = Image.alpha_composite(body, layer)

    # viền sáng
    rim_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(rim_mask).rounded_rectangle(
        (0, 0, W - 1, H - 1), R, outline=255, width=max(2, int(1.4 * K)))
    rim = _vgrad(W, H, (255, 255, 255, p["rim_top"]), (255, 255, 255, p["rim_bot"]))
    rim.putalpha(ImageChops.multiply(rim.getchannel("A"), rim_mask))
    out = Image.alpha_composite(body, rim)

    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    return out.resize((w * OUT, h * OUT), Image.LANCZOS)


class GlassButton(ctk.CTkLabel):
    def __init__(self, master, text, width, height, command=None,
                 boost=1.0, interactive=True, bg="#000000",
                 text_color="#ffffff", font=None):
        radius = height // 2
        self._imgs = {
            s: ctk.CTkImage(glass_image(width, height, radius, s, boost),
                            size=(width, height))
            for s in LEVELS
        }
        self._command = command
        self._interactive = interactive
        self._enabled = True
        self._inside = False
        self._text_color = text_color

        super().__init__(master, text=text, image=self._imgs["normal"],
                         compound="center", width=width, height=height,
                         fg_color=bg, text_color=text_color, font=font)

        if interactive:
            try:
                self._label.configure(cursor="hand2")
            except Exception:
                pass
            self.bind("<Enter>", self._on_enter)
            self.bind("<Leave>", self._on_leave)
            self.bind("<ButtonPress-1>", self._on_press)
            self.bind("<ButtonRelease-1>", self._on_release)

    def _show(self, state):
        self.configure(image=self._imgs[state])

    def _on_enter(self, _):
        self._inside = True
        if self._enabled:
            self._show("hover")

    def _on_leave(self, _):
        self._inside = False
        if self._enabled:
            self._show("normal")

    def _on_press(self, _):
        if self._enabled:
            self._show("press")

    def _on_release(self, _):
        if not self._enabled:
            return
        self._show("hover" if self._inside else "normal")
        if self._inside and self._command:
            self._command()

    def set_enabled(self, enabled):
        self._enabled = enabled
        self._show("normal" if enabled else "disabled")
        self.configure(text_color=self._text_color if enabled else "#8a8a8a")

    def set_text(self, text):
        self.configure(text=text)
