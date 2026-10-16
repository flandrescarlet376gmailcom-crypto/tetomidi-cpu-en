import os
from PyInstaller.utils.hooks import collect_all

datas, binaries, hidden = [], [], []
for pkg in ["transkun", "customtkinter"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

binaries += [("bin/ffmpeg.exe", "bin")]
if os.path.exists("assets/logo.png"):
    datas += [("assets/logo.png", "assets")]
if os.path.exists("assets/tetomidi.ico"):
    datas += [("assets/tetomidi.ico", "assets")]
icon = "assets/tetomidi.ico" if os.path.exists("assets/tetomidi.ico") else None

a = Analysis(["main.py"], binaries=binaries, datas=datas, hiddenimports=hidden)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="tetomidi", icon=icon, console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="tetomidi")
