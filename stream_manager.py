"""Unified stream manager - single RTSP connection for display, recording, and audio."""

import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from config import CameraConfig
from logger import get_logger

log = get_logger("stream_manager")


@dataclass
class StreamStats:
    """Statistics about the stream."""

    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    is_connected: bool = False
    is_recording: bool = False
    recording_duration: float = 0.0
    frames_received: int = 0
    frames_dropped: int = 0


class UnifiedStreamManager:
    """
    Manages a single RTSP connection that feeds both display and recording.

    Uses a single ffmpeg process to capture the stream and outputs to:
    - A pipe for raw frames (displayed in GUI via OpenCV)
    - An MP4 file (when recording is enabled)
    - Audio output (via ffplay subprocess)
    """

    # Health check settings
    HEALTH_CHECK_INTERVAL = 5.0
    FRAME_TIMEOUT = 10.0
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_DELAY = 2.0

    def __init__(self, camera: CameraConfig, output_dir: str | Path = "recordings"):
        self.camera = camera
        self.output_dir = Path(output_dir)

        # FFmpeg process for video capture
        self._ffmpeg_process: subprocess.Popen | None = None
        self._capture_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Frame handling
        self._frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._frame_callbacks: list[Callable[[np.ndarray], None]] = []
        self._last_frame_time = 0.0

        # Recording state
        self._is_recording = False
        self._recording_process: subprocess.Popen | None = None
        self._recording_thread: threading.Thread | None = None
        self._recording_stop_event = threading.Event()
        self._session_dir: Path | None = None
        self._current_recording_file: Path | None = None
        self._recording_start_time: datetime | None = None
        self._recorded_files: list[Path] = []
        self._record_audio = True

        # Audio
        self._audio_process: subprocess.Popen | None = None
        self._audio_enabled = False

        # Stats
        self._stats = StreamStats()
        self._reconnect_count = 0
        self._status_callback: Callable[[str], None] | None = None

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        """Set callback for status updates."""
        self._status_callback = callback

    def _notify_status(self, status: str) -> None:
        """Notify status callback."""
        if self._status_callback:
            try:
                self._status_callback(status)
            except Exception:
                pass

    def add_frame_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Add callback for new frames."""
        self._frame_callbacks.append(callback)

    def remove_frame_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Remove frame callback."""
        if callback in self._frame_callbacks:
            self._frame_callbacks.remove(callback)

    @property
    def stats(self) -> StreamStats:
        """Get current stream statistics."""
        return self._stats

    def get_frame(self) -> np.ndarray | None:
        """Get the latest frame."""
        with self._frame_lock:
            return self._frame

    def is_streaming(self) -> bool:
        """Check if stream is active."""
        return (
            self._capture_thread is not None
            and self._capture_thread.is_alive()
            and self._stats.is_connected
        )

    def is_recording(self) -> bool:
        """Check if recording is active."""
        return self._is_recording and self._recording_process is not None

    def start(self, enable_audio: bool = True) -> bool:
        """Start the unified stream."""
        if self.is_streaming():
            return True

        self._stop_event.clear()
        self._reconnect_count = 0
        self._audio_enabled = enable_audio

        self._notify_status("Connecting...")
        log.info(f"Starting unified stream for {self.camera.name}")

        if not self._start_capture():
            return False

        self._notify_status("Streaming")

        # Start audio if enabled
        if enable_audio:
            self._start_audio()

        return True

    def _start_capture(self) -> bool:
        """Start the ffmpeg capture process."""
        # Build ffmpeg command for raw frame output
        cmd = [
            "ffmpeg",
            "-rtsp_transport", "tcp",
            "-fflags", "+genpts+discardcorrupt",
            "-buffer_size", "8192000",
            "-i", self.camera.rtsp_url,
            "-an",  # No audio for frame capture
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-vsync", "0",
            "pipe:1",  # Output to stdout
        ]

        log.debug(f"Starting capture: {' '.join(cmd)}")

        try:
            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10 * 1024 * 1024,  # 10MB buffer
            )

            # Drain stderr in background
            threading.Thread(
                target=self._drain_stderr,
                args=(self._ffmpeg_process,),
                daemon=True,
            ).start()

            # Probe stream to get dimensions
            if not self._probe_stream():
                self._ffmpeg_process.terminate()
                return False

            # Start capture thread
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                daemon=True,
            )
            self._capture_thread.start()

            self._stats.is_connected = True
            log.info(
                f"Connected: {self._stats.width}x{self._stats.height} "
                f"@ {self._stats.fps:.1f}fps"
            )
            return True

        except Exception as e:
            log.error(f"Failed to start capture: {e}")
            return False

    def _probe_stream(self) -> bool:
        """Probe the stream to get video dimensions."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams",
                    "-rtsp_transport", "tcp",
                    self.camera.rtsp_url,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                log.error("Failed to probe stream")
                return False

            import json
            data = json.loads(result.stdout)

            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    self._stats.width = stream.get("width", 0)
                    self._stats.height = stream.get("height", 0)
                    self._stats.codec = stream.get("codec_name", "")

                    fps_str = stream.get("r_frame_rate", "30/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        if int(den) > 0:
                            self._stats.fps = int(num) / int(den)
                    return True

            return False

        except Exception as e:
            log.error(f"Probe error: {e}")
            return False

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        """Drain stderr to prevent blocking."""
        try:
            if proc.stderr:
                for line in proc.stderr:
                    pass  # Discard
        except Exception:
            pass

    def _capture_loop(self) -> None:
        """Read frames from ffmpeg stdout."""
        frame_size = self._stats.width * self._stats.height * 3  # BGR24
        fps_start = time.time()
        frame_count = 0

        log.debug(f"Capture loop started, frame size: {frame_size} bytes")

        while not self._stop_event.is_set():
            if self._ffmpeg_process is None or self._ffmpeg_process.poll() is not None:
                self._stats.is_connected = False
                log.warning("FFmpeg process ended, attempting reconnect...")
                if not self._reconnect():
                    break
                frame_size = self._stats.width * self._stats.height * 3
                continue

            try:
                raw_frame = self._ffmpeg_process.stdout.read(frame_size)
                if len(raw_frame) != frame_size:
                    self._stats.frames_dropped += 1
                    continue

                frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape(
                    (self._stats.height, self._stats.width, 3)
                )

                current_time = time.time()
                self._last_frame_time = current_time
                self._stats.frames_received += 1
                frame_count += 1

                # Update FPS
                elapsed = current_time - fps_start
                if elapsed >= 1.0:
                    self._stats.fps = frame_count / elapsed
                    frame_count = 0
                    fps_start = current_time

                # Store frame
                with self._frame_lock:
                    self._frame = frame

                # Notify callbacks
                for callback in self._frame_callbacks:
                    try:
                        callback(frame)
                    except Exception:
                        pass

            except Exception as e:
                log.error(f"Frame read error: {e}")
                self._stats.frames_dropped += 1

    def _reconnect(self) -> bool:
        """Attempt to reconnect the stream."""
        self._reconnect_count += 1
        log.warning(f"Reconnecting ({self._reconnect_count}/{self.MAX_RECONNECT_ATTEMPTS})...")
        self._notify_status(f"Reconnecting ({self._reconnect_count}/{self.MAX_RECONNECT_ATTEMPTS})...")

        if self._reconnect_count > self.MAX_RECONNECT_ATTEMPTS:
            log.error("Max reconnect attempts reached")
            self._notify_status("Connection failed")
            return False

        # Kill old process
        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=2.0)
            except Exception:
                pass

        time.sleep(self.RECONNECT_DELAY)

        if self._stop_event.is_set():
            return False

        if self._start_capture():
            self._reconnect_count = 0
            log.info("Reconnected successfully")
            self._notify_status("Reconnected")
            return True

        return False

    def _start_audio(self) -> None:
        """Start audio playback using ffplay."""
        if self._audio_process is not None:
            return

        cmd = [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-loglevel", "quiet",
            "-rtsp_transport", "tcp",
            "-sync", "audio",
            "-af", "aresample=async=1000",
            self.camera.rtsp_url,
        ]

        try:
            self._audio_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Audio playback started")
        except Exception as e:
            log.error(f"Failed to start audio: {e}")

    def _stop_audio(self) -> None:
        """Stop audio playback."""
        if self._audio_process:
            try:
                self._audio_process.terminate()
                self._audio_process.wait(timeout=2.0)
            except Exception:
                pass
            self._audio_process = None
            log.info("Audio playback stopped")

    def enable_audio(self) -> None:
        """Enable audio playback."""
        if not self._audio_enabled:
            self._audio_enabled = True
            if self.is_streaming():
                self._start_audio()

    def disable_audio(self) -> None:
        """Disable audio playback."""
        self._audio_enabled = False
        self._stop_audio()

    def start_recording(self, record_audio: bool = True) -> bool:
        """Start recording to a new session directory."""
        if self._is_recording:
            return True

        if not self.is_streaming():
            log.error("Cannot record: stream not active")
            return False

        self._record_audio = record_audio
        self._recording_stop_event.clear()
        self._recorded_files = []

        # Create session directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.camera.name)
        self._session_dir = self.output_dir / f"{safe_name}_{timestamp}"
        self._session_dir.mkdir(parents=True, exist_ok=True)

        self._recording_start_time = datetime.now()
        self._is_recording = True

        # Start recording thread
        self._recording_thread = threading.Thread(
            target=self._recording_loop,
            daemon=True,
        )
        self._recording_thread.start()

        log.info(f"Recording started: {self._session_dir}")
        return True

    def _recording_loop(self) -> None:
        """Recording loop - runs ffmpeg to save to file."""
        segment_duration = 30 * 60  # 30 minutes
        segment_number = 0
        consecutive_failures = 0
        max_failures = 5

        while not self._recording_stop_event.is_set() and self._is_recording:
            segment_number += 1

            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.camera.name)
            self._current_recording_file = self._session_dir / f"{safe_name}_{timestamp}.mp4"

            log.info(f"Starting recording segment {segment_number}: {self._current_recording_file.name}")

            # Build ffmpeg command
            cmd = [
                "ffmpeg",
                "-y",
                "-rtsp_transport", "tcp",
                "-fflags", "+genpts+discardcorrupt",
                "-buffer_size", "8192000",
                "-i", self.camera.rtsp_url,
                "-c:v", "copy",
            ]

            if self._record_audio:
                cmd.extend(["-c:a", "aac", "-b:a", "128k"])
            else:
                cmd.extend(["-an"])

            cmd.extend([
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                str(self._current_recording_file),
            ])

            stderr_lines: list[str] = []

            try:
                self._recording_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )

                # Drain stderr
                def drain(proc, lines):
                    try:
                        if proc.stderr:
                            for line in proc.stderr:
                                lines.append(line.decode("utf-8", errors="replace").strip())
                    except Exception:
                        pass

                stderr_thread = threading.Thread(target=drain, args=(self._recording_process, stderr_lines), daemon=True)
                stderr_thread.start()

                # Wait for segment duration or stop
                segment_start = time.time()
                segment_failed = False

                while not self._recording_stop_event.is_set():
                    exit_code = self._recording_process.poll()
                    if exit_code is not None:
                        elapsed = time.time() - segment_start
                        if exit_code != 0 or elapsed < 5.0:
                            log.error(f"Recording ffmpeg exited with code {exit_code} after {elapsed:.1f}s")
                            stderr_thread.join(timeout=1.0)
                            for line in stderr_lines[-10:]:
                                log.error(f"  ffmpeg: {line}")
                            segment_failed = True
                        break

                    elapsed = time.time() - segment_start
                    if elapsed >= segment_duration:
                        log.info(f"Segment {segment_number} reached duration limit, rotating...")
                        break

                    self._recording_stop_event.wait(0.5)

                # Graceful stop
                self._stop_recording_process()
                stderr_thread.join(timeout=2.0)

                if segment_failed:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        log.error("Too many recording failures, stopping")
                        break
                    log.info("Waiting 5s before retry...")
                    if self._recording_stop_event.wait(5.0):
                        break
                    continue

                consecutive_failures = 0

                # Track file
                if self._current_recording_file.exists():
                    size = self._current_recording_file.stat().st_size
                    if size > 0:
                        self._recorded_files.append(self._current_recording_file)
                        log.info(f"Segment {segment_number} saved: {size / 1024 / 1024:.2f} MB")

            except Exception as e:
                log.exception(f"Recording error: {e}")
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    break
                if self._recording_stop_event.wait(5.0):
                    break

        self._is_recording = False
        self._stats.is_recording = False
        log.info(f"Recording stopped. Total segments: {len(self._recorded_files)}")

    def _stop_recording_process(self) -> None:
        """Gracefully stop the recording ffmpeg process."""
        if self._recording_process is None:
            return

        proc = self._recording_process
        self._recording_process = None

        if proc.poll() is not None:
            return

        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
        except Exception:
            pass

        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop_recording(self) -> Path | None:
        """Stop recording and return session directory."""
        if not self._is_recording:
            return None

        log.info("Stopping recording...")
        self._recording_stop_event.set()
        self._is_recording = False

        if self._recording_thread:
            self._recording_thread.join(timeout=10.0)
            self._recording_thread = None

        session_dir = self._session_dir
        self._session_dir = None
        self._recording_start_time = None

        return session_dir

    def get_recording_duration(self) -> float:
        """Get current recording duration in seconds."""
        if self._recording_start_time and self._is_recording:
            return (datetime.now() - self._recording_start_time).total_seconds()
        return 0.0

    def get_recorded_files(self) -> list[Path]:
        """Get list of recorded files."""
        return self._recorded_files.copy()

    def stop(self) -> None:
        """Stop all streaming and recording."""
        log.info("Stopping unified stream manager...")

        self._stop_event.set()

        # Stop recording first
        if self._is_recording:
            self.stop_recording()

        # Stop audio
        self._stop_audio()

        # Stop capture
        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=2.0)
            except Exception:
                pass
            self._ffmpeg_process = None

        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None

        self._stats.is_connected = False
        self._frame = None

        log.info("Stream manager stopped")
