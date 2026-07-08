"""
utils/logger.py

Centralized logging configuration. Every module gets a logger via
`get_logger(__name__)` so log lines are traceable to their source, and
everything is written both to a rotating log file (for audit purposes in
a business environment) and to the console during development.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.expanduser("~"), "DateRangeValidator_Output", "logs")
LOG_FILE = os.path.join(LOG_DIR, "date_range_validator.log")

_configured = False


def _configure_root_logger() -> None:
    global _configured
    if _configured:
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger("date_range_validator")
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger scoped under the application's root logger.

    Usage: logger = get_logger(__name__)
    """
    _configure_root_logger()
    return logging.getLogger(f"date_range_validator.{name}")
