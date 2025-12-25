"""Utility modules for RTSP Viewer."""

from rtsp_viewer.utils.logger import get_logger, add_gui_handler, remove_gui_handler, GUILogHandler
from rtsp_viewer.utils.state import AppState

__all__ = [
    "get_logger",
    "add_gui_handler",
    "remove_gui_handler",
    "GUILogHandler",
    "AppState",
]
