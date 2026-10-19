import os
from PyInstaller.utils.hooks import collect_all

# Thin client: only the GUI is bundled (no Transkun, no ffmpeg, no yt-dlp)
datas, binaries, hidden = collect_all("customtkinter")

for asset in ["assets/logo.png", "assets/tetomidi.ico", "assets/discord.png"]:
    if os.path.exists(asset):
        datas += [(asset, "assets")]
icon = "assets/tetomidi.ico" if os.path.exists("assets/tetomidi.ico") else None

a = Analysis(["main.py"], binaries=binaries, datas=datas, hiddenimports=hidden)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="tetomidi", icon=icon, console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="tetomidi")
