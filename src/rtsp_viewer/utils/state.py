"""State persistence for RTSP Viewer."""

import json
from pathlib import Path

from rtsp_viewer.utils.logger import get_logger

log = get_logger("state")

DEFAULT_STATE_FILE = Path.home() / ".config" / "rtsp_viewer" / "state.json"


class AppState:
    """Manages persistent application state."""

    def __init__(self, state_file: Path = DEFAULT_STATE_FILE):
        self.state_file = state_file
        self._state: dict = {}
        self._load()

    def _load(self) -> None:
        """Load state from file."""
        if self.state_file.exists():
            try:
                self._state = json.loads(self.state_file.read_text())
                log.debug(f"Loaded state from {self.state_file}")
            except Exception as e:
                log.warning(f"Failed to load state: {e}")
                self._state = {}
        else:
            self._state = {}

    def save(self) -> None:
        """Save state to file."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self._state, indent=2))
            log.debug(f"Saved state to {self.state_file}")
        except Exception as e:
            log.warning(f"Failed to save state: {e}")

    def get(self, key: str, default=None):
        """Get a state value."""
        return self._state.get(key, default)

    def set(self, key: str, value) -> None:
        """Set a state value."""
        self._state[key] = value

    # Convenience properties for common settings
    @property
    def last_camera(self) -> str | None:
        """Get the last selected camera name."""
        return self.get("last_camera")

    @last_camera.setter
    def last_camera(self, name: str) -> None:
        """Set the last selected camera name."""
        self.set("last_camera", name)

    @property
    def audio_preview_enabled(self) -> bool:
        """Get audio preview preference."""
        return self.get("audio_preview_enabled", True)

    @audio_preview_enabled.setter
    def audio_preview_enabled(self, enabled: bool) -> None:
        """Set audio preview preference."""
        self.set("audio_preview_enabled", enabled)

    @property
    def record_audio_enabled(self) -> bool:
        """Get record audio preference."""
        return self.get("record_audio_enabled", True)

    @record_audio_enabled.setter
    def record_audio_enabled(self, enabled: bool) -> None:
        """Set record audio preference."""
        self.set("record_audio_enabled", enabled)

    @property
    def console_visible(self) -> bool:
        """Get console visibility preference."""
        return self.get("console_visible", False)

    @console_visible.setter
    def console_visible(self, visible: bool) -> None:
        """Set console visibility preference."""
        self.set("console_visible", visible)

    # Streamer GUI settings
    @property
    def streamer_last_video(self) -> str | None:
        """Get the last selected video file path for streamer."""
        return self.get("streamer_last_video")

    @streamer_last_video.setter
    def streamer_last_video(self, path: str | None) -> None:
        """Set the last selected video file path for streamer."""
        self.set("streamer_last_video", path)

    @property
    def streamer_show_preview(self) -> bool:
        """Get streamer preview preference."""
        return self.get("streamer_show_preview", True)

    @streamer_show_preview.setter
    def streamer_show_preview(self, enabled: bool) -> None:
        """Set streamer preview preference."""
        self.set("streamer_show_preview", enabled)

    @property
    def streamer_audio_enabled(self) -> bool:
        """Get streamer audio preference."""
        return self.get("streamer_audio_enabled", True)

    @streamer_audio_enabled.setter
    def streamer_audio_enabled(self, enabled: bool) -> None:
        """Set streamer audio preference."""
        self.set("streamer_audio_enabled", enabled)
