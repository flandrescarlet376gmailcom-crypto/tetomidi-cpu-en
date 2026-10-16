import os
import sys


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel)


def setup_ffmpeg():
    # Put bundled ffmpeg at the front of PATH
    os.environ["PATH"] = resource_path("bin") + os.pathsep + os.environ["PATH"]
