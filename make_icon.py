import os
from PIL import Image

SRC = "assets/logo.png"
DST = "assets/tetomidi.ico"

if os.path.exists(SRC):
    img = Image.open(SRC).convert("RGBA")

    # cắt sát phần hình sáng rồi chừa lề nhỏ
    mask = img.convert("L").point(lambda v: 255 if v > 60 else 0)
    box = mask.getbbox()
    if box:
        l, t, r, b = box
        side = int(max(r - l, b - t) * 1.18)
        cx, cy = (l + r) // 2, (t + b) // 2
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 255))
        canvas.paste(img, (-(cx - side // 2), -(cy - side // 2)))
        img = canvas

    img = img.resize((256, 256), Image.LANCZOS)
    img.save(DST, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                         (64, 64), (128, 128), (256, 256)])
