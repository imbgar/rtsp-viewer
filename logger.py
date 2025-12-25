"""Logging configuration for RTSP Viewer."""

import logging
import sys
from collections.abc import Callable

# Create logger
logger = logging.getLogger("rtsp_viewer")
logger.setLevel(logging.DEBUG)

# Create console handler with formatting
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Create formatter with timestamp
formatter = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
console_handler.setFormatter(formatter)

# Add handler to logger
logger.addHandler(console_handler)


class GUILogHandler(logging.Handler):
    """Custom log handler that sends log messages to a callback."""

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self.callback = callback
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.callback(msg)
        except Exception:
            pass


def add_gui_handler(callback: Callable[[str], None]) -> GUILogHandler:
    """Add a GUI handler that sends log messages to the given callback."""
    handler = GUILogHandler(callback)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return handler


def remove_gui_handler(handler: GUILogHandler) -> None:
    """Remove a GUI handler."""
    logger.removeHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger with the given name."""
    return logger.getChild(name)
