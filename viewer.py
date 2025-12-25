"""Main RTSP Viewer controller using unified stream."""

from collections.abc import Callable
from pathlib import Path

import numpy as np

from config import CameraConfig, load_cameras
from unified_stream import UnifiedStream, StreamStats


class RTSPViewer:
    """Main controller for the RTSP viewer application."""

    def __init__(self, config_path: str | Path = "cameras.yaml"):
        self.config_path = Path(config_path)
        self._cameras: list[CameraConfig] = []
        self._current_camera_index: int = -1

        # Unified stream manager
        self._stream: UnifiedStream | None = None

        # Callbacks
        self._status_callback: Callable[[str], None] | None = None

        # Load initial configuration
        self.reload_config()

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        """Set a callback to receive stream status updates."""
        self._status_callback = callback

    def reload_config(self) -> None:
        """Reload camera configuration from file."""
        try:
            self._cameras = load_cameras(self.config_path)
            if self._cameras and self._current_camera_index < 0:
                self._current_camera_index = 0
        except FileNotFoundError:
            self._cameras = []
            self._current_camera_index = -1

    def get_cameras(self) -> list[CameraConfig]:
        """Get list of configured cameras."""
        return self._cameras

    def select_camera(self, index: int) -> bool:
        """Select a camera by index."""
        if 0 <= index < len(self._cameras):
            # Stop current stream if active
            self.stop_stream()
            self._current_camera_index = index
            return True
        return False

    def get_current_camera(self) -> CameraConfig | None:
        """Get the currently selected camera configuration."""
        if 0 <= self._current_camera_index < len(self._cameras):
            return self._cameras[self._current_camera_index]
        return None

    def start_stream(self, enable_audio: bool = True) -> bool:
        """Start streaming from the current camera."""
        camera = self.get_current_camera()
        if camera is None:
            return False

        # Create unified stream
        self._stream = UnifiedStream(camera)

        # Wire up status callback
        if self._status_callback:
            self._stream.set_status_callback(self._status_callback)

        return self._stream.start(enable_audio=enable_audio)

    def stop_stream(self) -> None:
        """Stop the current stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream = None

    def is_streaming(self) -> bool:
        """Check if currently streaming."""
        return self._stream is not None and self._stream.is_streaming()

    def get_frame(self) -> np.ndarray | None:
        """Get the latest video frame."""
        if self._stream is not None:
            return self._stream.get_frame()
        return None

    def get_stream_info(self) -> StreamStats:
        """Get current stream information."""
        if self._stream is not None:
            return self._stream.stats
        return StreamStats()

    def get_actual_fps(self) -> float:
        """Get actual measured FPS."""
        if self._stream is not None:
            return self._stream.stats.fps
        return 0.0

    def enable_audio(self) -> None:
        """Enable audio playback."""
        if self._stream is not None:
            self._stream.enable_audio()

    def disable_audio(self) -> None:
        """Disable audio playback."""
        if self._stream is not None:
            self._stream.disable_audio()

    def start_recording(self, record_audio: bool = True) -> bool:
        """Start recording the current stream."""
        if self._stream is None:
            return False
        return self._stream.start_recording(record_audio=record_audio)

    def stop_recording(self) -> Path | None:
        """Stop recording and return the path to the recorded file."""
        if self._stream is not None:
            return self._stream.stop_recording()
        return None

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._stream is not None and self._stream.is_recording()

    def get_recording_duration(self) -> float:
        """Get current recording duration in seconds."""
        if self._stream is not None:
            return self._stream.get_recording_duration()
        return 0.0

    def stop_all(self) -> None:
        """Stop all active components."""
        self.stop_stream()
