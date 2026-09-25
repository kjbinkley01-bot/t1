#!/usr/bin/env python3
"""Start Clicker. Run with: python clicker_app.py"""

import sys


def main():
    try:
        from clicker.qt.app import main as glass_main
    except ImportError as e:
        sys.exit(f"Clicker needs PySide6: python -m pip install -r requirements.txt ({e})")
    return glass_main()


if __name__ == "__main__":
    main()
