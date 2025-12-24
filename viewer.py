"""Main RTSP Viewer controller that integrates all components."""

from pathlib import Path

import numpy as np

from audio import AudioPlayer
from config import CameraConfig, load_cameras
from recorder import Recorder, StreamProbe
from stream import RTSPStreamHandler, StreamInfo


class RTSPViewer:
    """Main controller for the RTSP viewer application."""

    def __init__(self, config_path: str | Path = "cameras.yaml"):
        self.config_path = Path(config_path)
        self._cameras: list[CameraConfig] = []
        self._current_camera_index: int = -1

        # Components
        self._stream_handler: RTSPStreamHandler | None = None
        self._audio_player: AudioPlayer | None = None
        self._recorder: Recorder | None = None

        # Load initial configuration
        self.reload_config()

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

        # Create stream handler
        self._stream_handler = RTSPStreamHandler(camera)
        success = self._stream_handler.start()

        if not success:
            self._stream_handler = None
            return False

        # Start audio if enabled
        if enable_audio:
            self._audio_player = AudioPlayer(camera)
            self._audio_player.start()

        # Create recorder (but don't start it yet)
        self._recorder = Recorder(camera)

        return True

    def stop_stream(self) -> None:
        """Stop the current stream."""
        # Stop recording if active
        if self._recorder is not None and self._recorder.is_recording():
            self._recorder.stop()

        # Stop audio
        if self._audio_player is not None:
            self._audio_player.stop()
            self._audio_player = None

        # Stop video stream
        if self._stream_handler is not None:
            self._stream_handler.stop()
            self._stream_handler = None

        self._recorder = None

    def is_streaming(self) -> bool:
        """Check if currently streaming."""
        return self._stream_handler is not None and self._stream_handler.is_running()

    def get_frame(self) -> np.ndarray | None:
        """Get the latest video frame."""
        if self._stream_handler is not None:
            return self._stream_handler.get_frame()
        return None

    def get_stream_info(self) -> StreamInfo:
        """Get current stream information."""
        if self._stream_handler is not None:
            return self._stream_handler.stream_info
        return StreamInfo()

    def get_actual_fps(self) -> float:
        """Get actual measured FPS."""
        if self._stream_handler is not None:
            return self._stream_handler.actual_fps
        return 0.0

    def enable_audio(self) -> None:
        """Enable audio playback."""
        if self._audio_player is not None and not self._audio_player.is_playing():
            self._audio_player.start()
        elif self._audio_player is None and self.is_streaming():
            camera = self.get_current_camera()
            if camera is not None:
                self._audio_player = AudioPlayer(camera)
                self._audio_player.start()

    def disable_audio(self) -> None:
        """Disable audio playback."""
        if self._audio_player is not None:
            self._audio_player.stop()

    def start_recording(self, record_audio: bool = True) -> bool:
        """Start recording the current stream."""
        if not self.is_streaming():
            return False

        if self._recorder is None:
            camera = self.get_current_camera()
            if camera is None:
                return False
            self._recorder = Recorder(camera)

        return self._recorder.start(record_audio=record_audio)

    def stop_recording(self) -> Path | None:
        """Stop recording and return the path to the recorded file."""
        if self._recorder is not None:
            return self._recorder.stop()
        return None

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recorder is not None and self._recorder.is_recording()

    def get_recording_duration(self) -> float:
        """Get current recording duration in seconds."""
        if self._recorder is not None:
            return self._recorder.get_recording_duration()
        return 0.0

    def probe_stream(self) -> dict:
        """Probe the current camera stream for detailed info."""
        camera = self.get_current_camera()
        if camera is None:
            return {}
        return StreamProbe.get_stream_info(camera.rtsp_url)

    def stop_all(self) -> None:
        """Stop all active components."""
        self.stop_stream()
