#!/usr/bin/env python3
"""Music Downloader -- GUI application for downloading music from YouTube/Spotify.

Usage:
    python main.py            Launch the graphical interface.

For the command-line version:
    python descargar.py [album]
    python stats.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import run

if __name__ == "__main__":
    run()
