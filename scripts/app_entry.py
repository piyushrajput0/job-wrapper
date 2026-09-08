"""Entry point for the packaged desktop application."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()          # PyInstaller + threads on macOS
    from jobwrapper.desktop import main

    sys.exit(main() or 0)
