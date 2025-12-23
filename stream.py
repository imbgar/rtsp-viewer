"""RTSP stream handler using OpenCV with low-latency optimizations."""

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

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
    latency_ms: float = 0.0


class RTSPStreamHandler:
    """Handles RTSP stream capture using OpenCV with low-latency optimizations."""

    def __init__(self, camera: CameraConfig):
        self.camera = camera
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._frame_callbacks: list[Callable[[np.ndarray], None]] = []
        self._stream_info = StreamInfo()
        self._frame_timestamp = 0.0
        self._actual_fps = 0.0
        self._dropped_frames = 0
        self._total_frames = 0

    @property
    def stream_info(self) -> StreamInfo:
        """Get current stream information."""
        return self._stream_info

    @property
    def actual_fps(self) -> float:
        """Get the actual measured FPS."""
        return self._actual_fps

    @property
    def dropped_frames(self) -> int:
        """Get count of dropped frames."""
        return self._dropped_frames

    def add_frame_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Add a callback to be called when a new frame is available."""
        self._frame_callbacks.append(callback)

    def remove_frame_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Remove a frame callback."""
        if callback in self._frame_callbacks:
            self._frame_callbacks.remove(callback)

    def _build_rtsp_url_with_options(self) -> str:
        """Build RTSP URL with ffmpeg options for low latency."""
        # Use TCP transport for reliability, minimize buffer
        # Format: rtsp://user:pass@host:port/path?options
        base_url = self.camera.rtsp_url
        return base_url

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

    def start(self, use_tcp: bool = True) -> bool:
        """
        Start the stream capture.

        Args:
            use_tcp: Use TCP transport (more reliable, slightly higher latency)
        """
        if self._thread is not None and self._thread.is_alive():
            return True

        self._stop_event.clear()
        self._dropped_frames = 0
        self._total_frames = 0

        # Check if low_latency is enabled in camera config
        low_latency = self.camera.low_latency

        # Set FFmpeg options via environment for low latency
        # These affect how FFmpeg (used by OpenCV) handles the stream
        if low_latency:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|"  # TCP for reliability
                "fflags;nobuffer|"  # Disable buffering
                "flags;low_delay|"  # Low delay mode
                "framedrop;1|"  # Allow frame dropping
                "strict;experimental|"
                "avioflags;direct|"  # Direct I/O
                "fflags;discardcorrupt|"  # Discard corrupt frames
                "analyzeduration;500000|"  # Reduce analyze time (500ms)
                "probesize;500000"  # Reduce probe size
            )
        elif use_tcp:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        # Create capture with FFmpeg backend
        self._cap = cv2.VideoCapture(self.camera.rtsp_url, cv2.CAP_FFMPEG)

        if not self._cap.isOpened():
            self._stream_info.is_connected = False
            return False

        # Minimal buffer - we want the latest frame, not queued frames
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

        # Clean up environment
        if "OPENCV_FFMPEG_CAPTURE_OPTIONS" in os.environ:
            del os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]

    def _capture_loop(self) -> None:
        """Main capture loop with optional frame dropping for real-time performance."""
        fps_update_interval = 1.0
        frame_count = 0
        fps_start_time = time.time()
        low_latency = self.camera.low_latency

        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._stream_info.is_connected = False
                break

            frame_start = time.time()

            if low_latency:
                # Low-latency mode: grab multiple frames and only decode the latest
                # This drains the buffer and reduces latency
                grabbed = False
                for _ in range(3):  # Try to grab up to 3 frames
                    if self._cap.grab():
                        grabbed = True
                        self._total_frames += 1
                    else:
                        break

                if not grabbed:
                    time.sleep(0.01)
                    continue

                # Only decode the last grabbed frame
                ret, frame = self._cap.retrieve()
            else:
                # Standard mode: read frames normally without dropping
                ret, frame = self._cap.read()
                self._total_frames += 1

            if not ret or frame is None:
                self._dropped_frames += 1
                continue

            current_time = time.time()
            decode_time = current_time - frame_start

            # Update FPS calculation
            frame_count += 1
            elapsed = current_time - fps_start_time
            if elapsed >= fps_update_interval:
                self._actual_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = current_time

            # Store the frame with minimal locking
            with self._frame_lock:
                self._frame = frame
                self._frame_timestamp = current_time
                self._stream_info.latency_ms = decode_time * 1000

            # Notify callbacks
            for callback in self._frame_callbacks:
                try:
                    callback(frame)
                except Exception:
                    pass

    def get_frame(self) -> np.ndarray | None:
        """Get the latest frame without copying (for performance)."""
        with self._frame_lock:
            return self._frame

    def get_frame_copy(self) -> np.ndarray | None:
        """Get a copy of the latest frame (thread-safe for modifications)."""
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
