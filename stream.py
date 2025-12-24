"""RTSP stream handler using OpenCV with low-latency optimizations."""

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from config import CameraConfig
from logger import get_logger

log = get_logger("stream")


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

    # Health check settings
    HEALTH_CHECK_INTERVAL = 5.0  # Check every 5 seconds
    FRAME_TIMEOUT = 10.0  # Consider stream dead if no frame for 10 seconds
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_DELAY = 2.0  # Seconds between reconnect attempts

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
        self._last_frame_time = 0.0
        self._reconnect_count = 0
        self._status_callback: Callable[[str], None] | None = None

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

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        """Set a callback to receive status updates (connecting, reconnecting, etc.)."""
        self._status_callback = callback

    def _notify_status(self, status: str) -> None:
        """Notify status callback if set."""
        if self._status_callback:
            try:
                self._status_callback(status)
            except Exception:
                pass

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

    def _connect(self) -> bool:
        """Establish connection to the RTSP stream."""
        log.info(f"Connecting to {self.camera.name} at {self.camera.address}:{self.camera.port}")

        # Release existing capture if any
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        # Check if low_latency is enabled in camera config
        low_latency = self.camera.low_latency

        # Set FFmpeg options via environment
        # Always use TCP for reliability (UDP can drop packets)
        if low_latency:
            log.debug("Using low-latency mode")
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|"
                "fflags;nobuffer|"
                "flags;low_delay|"
                "framedrop;1|"
                "strict;experimental|"
                "avioflags;direct|"
                "fflags;discardcorrupt|"
                "analyzeduration;500000|"
                "probesize;500000"
            )
        else:
            log.debug("Using standard mode with TCP")
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|"
                "buffer_size;8192000|"
                "fflags;discardcorrupt"
            )

        # Create capture with FFmpeg backend
        self._cap = cv2.VideoCapture(self.camera.rtsp_url, cv2.CAP_FFMPEG)

        if not self._cap.isOpened():
            log.error(f"Failed to open stream: {self.camera.name}")
            self._stream_info.is_connected = False
            return False

        # Minimal buffer - we want the latest frame, not queued frames
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._detect_stream_info()
        self._last_frame_time = time.time()

        log.info(
            f"Connected: {self._stream_info.width}x{self._stream_info.height} "
            f"@ {self._stream_info.fps:.1f}fps ({self._stream_info.codec})"
        )
        return True

    def _reconnect(self) -> bool:
        """Attempt to reconnect to the stream."""
        self._reconnect_count += 1
        log.warning(f"Reconnecting ({self._reconnect_count}/{self.MAX_RECONNECT_ATTEMPTS})...")
        self._notify_status(f"Reconnecting ({self._reconnect_count}/{self.MAX_RECONNECT_ATTEMPTS})...")

        if self._reconnect_count > self.MAX_RECONNECT_ATTEMPTS:
            log.error("Connection failed - max retries exceeded")
            self._notify_status("Connection failed - max retries exceeded")
            return False

        # Wait before reconnecting
        time.sleep(self.RECONNECT_DELAY)

        if self._stop_event.is_set():
            return False

        if self._connect():
            self._reconnect_count = 0
            log.info("Reconnected successfully")
            self._notify_status("Reconnected")
            return True

        return False

    def start(self) -> bool:
        """Start the stream capture (always uses TCP for reliability)."""
        if self._thread is not None and self._thread.is_alive():
            return True

        self._stop_event.clear()
        self._dropped_frames = 0
        self._total_frames = 0
        self._reconnect_count = 0

        self._notify_status("Connecting...")

        if not self._connect():
            return False

        self._notify_status("Streaming")

        # Start capture thread
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        log.info("Stream capture thread started")
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
        """Main capture loop with health checking and auto-reconnect."""
        fps_update_interval = 1.0
        frame_count = 0
        fps_start_time = time.time()
        last_health_check = time.time()
        consecutive_failures = 0
        max_consecutive_failures = 30  # ~1 second of failures at 30fps

        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._stream_info.is_connected = False
                # Try to reconnect
                if not self._reconnect():
                    break
                consecutive_failures = 0
                continue

            current_time = time.time()
            frame_start = current_time
            low_latency = self.camera.low_latency

            # Health check: verify we're still receiving frames
            if current_time - last_health_check >= self.HEALTH_CHECK_INTERVAL:
                last_health_check = current_time
                time_since_last_frame = current_time - self._last_frame_time

                if time_since_last_frame > self.FRAME_TIMEOUT:
                    self._notify_status("Stream timeout - reconnecting...")
                    self._stream_info.is_connected = False
                    if not self._reconnect():
                        break
                    consecutive_failures = 0
                    continue

            if low_latency:
                # Low-latency mode: grab multiple frames and only decode the latest
                grabbed = False
                for _ in range(3):
                    if self._cap.grab():
                        grabbed = True
                        self._total_frames += 1
                    else:
                        break

                if not grabbed:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        self._notify_status("Stream stalled - reconnecting...")
                        self._stream_info.is_connected = False
                        if not self._reconnect():
                            break
                        consecutive_failures = 0
                    else:
                        time.sleep(0.01)
                    continue

                ret, frame = self._cap.retrieve()
            else:
                # Standard mode: read frames normally without dropping
                ret, frame = self._cap.read()
                self._total_frames += 1

            if not ret or frame is None:
                self._dropped_frames += 1
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    self._notify_status("Stream stalled - reconnecting...")
                    self._stream_info.is_connected = False
                    if not self._reconnect():
                        break
                    consecutive_failures = 0
                continue

            # Reset failure counter on successful frame
            consecutive_failures = 0
            current_time = time.time()
            decode_time = current_time - frame_start
            self._last_frame_time = current_time

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
