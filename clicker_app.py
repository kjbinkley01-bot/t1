#!/usr/bin/env python3
"""Start Clicker. Run with: python clicker_app.py  [--classic | --glass]

The Liquid Glass look (Qt) is used when PySide6 is installed, unless Settings or
--classic chose the Classic look.
"""

import sys


def main():
    from clicker import storage
    args = set(sys.argv[1:])
    ui = "classic" if "--classic" in args else "glass" if "--glass" in args else \
        storage.load_settings().get("ui", "glass")
    if ui == "glass":
        try:
            from clicker.qt.app import main as glass_main
        except ImportError:
            ui = "classic"  # PySide6 not installed: fall back to Classic
        else:
            return glass_main()
    from clicker.app import main as classic_main
    return classic_main()


if __name__ == "__main__":
    main()
