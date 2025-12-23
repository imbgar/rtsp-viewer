"""RTSP stream handler using OpenCV."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from config import CameraConfig


@dataclass
class StreamInfo:
    """Information about the current stream."""

    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    is_connected: bool = False


class RTSPStreamHandler:
    """Handles RTSP stream capture using OpenCV."""

    def __init__(self, camera: CameraConfig):
        self.camera = camera
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._frame_callbacks: list[Callable[[np.ndarray], None]] = []
        self._stream_info = StreamInfo()
        self._last_frame_time = 0.0
        self._actual_fps = 0.0

    @property
    def stream_info(self) -> StreamInfo:
        """Get current stream information."""
        return self._stream_info

    @property
    def actual_fps(self) -> float:
        """Get the actual measured FPS."""
        return self._actual_fps

    def add_frame_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Add a callback to be called when a new frame is available."""
        self._frame_callbacks.append(callback)

    def remove_frame_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Remove a frame callback."""
        if callback in self._frame_callbacks:
            self._frame_callbacks.remove(callback)

    def _detect_stream_info(self) -> None:
        """Detect stream properties from the capture device."""
        if self._cap is None:
            return

        self._stream_info.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._stream_info.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._stream_info.fps = self._cap.get(cv2.CAP_PROP_FPS)

        # Try to get codec info
        fourcc = int(self._cap.get(cv2.CAP_PROP_FOURCC))
        if fourcc > 0:
            self._stream_info.codec = "".join(
                [chr((fourcc >> 8 * i) & 0xFF) for i in range(4)]
            )

        self._stream_info.is_connected = True

    def start(self) -> bool:
        """Start the stream capture."""
        if self._thread is not None and self._thread.is_alive():
            return True

        self._stop_event.clear()

        # Configure OpenCV for RTSP
        # Using FFmpeg backend for better RTSP support
        self._cap = cv2.VideoCapture(self.camera.rtsp_url, cv2.CAP_FFMPEG)

        if not self._cap.isOpened():
            self._stream_info.is_connected = False
            return False

        # Set buffer size to minimize latency
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._detect_stream_info()

        # Start capture thread
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        return True

    def stop(self) -> None:
        """Stop the stream capture."""
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._cap is not None:
            self._cap.release()
            self._cap = None

        self._stream_info.is_connected = False
        self._frame = None

    def _capture_loop(self) -> None:
        """Main capture loop running in a separate thread."""
        fps_update_interval = 1.0
        frame_count = 0
        fps_start_time = time.time()

        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._stream_info.is_connected = False
                break

            ret, frame = self._cap.read()

            if not ret:
                # Try to reconnect
                time.sleep(0.1)
                continue

            current_time = time.time()

            # Update FPS calculation
            frame_count += 1
            elapsed = current_time - fps_start_time
            if elapsed >= fps_update_interval:
                self._actual_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = current_time

            # Store the frame
            with self._frame_lock:
                self._frame = frame
                self._last_frame_time = current_time

            # Notify callbacks
            for callback in self._frame_callbacks:
                try:
                    callback(frame)
                except Exception:
                    pass

    def get_frame(self) -> np.ndarray | None:
        """Get the latest frame."""
        with self._frame_lock:
            if self._frame is not None:
                return self._frame.copy()
            return None

    def is_running(self) -> bool:
        """Check if the stream is currently running."""
        return (
            self._thread is not None
            and self._thread.is_alive()
            and self._stream_info.is_connected
        )
