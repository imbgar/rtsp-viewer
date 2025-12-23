"""Audio playback handler using ffmpeg/ffplay."""

import shutil
import subprocess
import threading

from config import CameraConfig


class AudioPlayer:
    """Handles audio playback from RTSP stream using ffplay."""

    def __init__(self, camera: CameraConfig):
        self.camera = camera
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_playing = False

    @staticmethod
    def is_available() -> bool:
        """Check if ffplay is available on the system."""
        return shutil.which("ffplay") is not None

    def start(self) -> bool:
        """Start audio playback."""
        if not self.is_available():
            print("Warning: ffplay not found. Audio playback disabled.")
            return False

        if self._is_playing:
            return True

        self._stop_event.clear()

        # Start ffplay in a separate thread
        self._thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._thread.start()

        return True

    def _playback_loop(self) -> None:
        """Run ffplay for audio playback."""
        cmd = [
            "ffplay",
            "-nodisp",  # No video display (audio only)
            "-vn",  # Disable video
            "-autoexit",  # Exit when stream ends
            "-loglevel",
            "quiet",  # Suppress output
            "-i",
            self.camera.rtsp_url,
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._is_playing = True

            # Wait for process to end or stop event
            while not self._stop_event.is_set():
                if self._process.poll() is not None:
                    # Process ended
                    break
                self._stop_event.wait(0.1)

        except Exception as e:
            print(f"Audio playback error: {e}")
        finally:
            self._is_playing = False
            if self._process is not None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                self._process = None

    def stop(self) -> None:
        """Stop audio playback."""
        self._stop_event.set()

        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        self._is_playing = False

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self._is_playing and self._process is not None

    def set_volume(self, volume: int) -> None:
        """
        Set playback volume (0-100).

        Note: ffplay doesn't support runtime volume changes.
        This would require restarting the stream with -volume flag.
        """
        pass
