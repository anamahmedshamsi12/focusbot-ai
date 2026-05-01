"""
main.py

Entry point for alfred.ai.

Run this file to launch the application:
    python -m focusbot
or after installing:
    focusbot
"""

import tkinter as tk

from focusbot.gui import FocusBotApp


def main() -> None:
    """Create the tkinter root window and launch alfred.ai."""
    root = tk.Tk()
    FocusBotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
    