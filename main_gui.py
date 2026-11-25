"""
Convenience launcher alias (`python main_gui.py`) for the Rehabilitation Monitor GUI.
Delegates directly to `gui_main.launch_gui()`.
"""
from __future__ import annotations

import sys

from gui_main import launch_gui

if __name__ == "__main__":
    sys.exit(launch_gui())
