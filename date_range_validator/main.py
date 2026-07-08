"""
main.py

Entry point for the Date Range Validator desktop application.

Run with:
    python main.py
"""

from __future__ import annotations

import multiprocessing
import sys

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from utils.logger import get_logger

logger = get_logger(__name__)


def main() -> int:
    # Required on Windows when using ProcessPoolExecutor from a frozen or
    # script-launched GUI app, so worker processes don't re-import and
    # re-launch the GUI themselves.
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)
    app.setApplicationName("Date Range Validator")

    window = MainWindow()
    window.show()

    logger.info("Date Range Validator started.")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
