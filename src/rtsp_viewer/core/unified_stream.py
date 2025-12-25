"""Unified stream manager - OpenCV for display, ffmpeg for recording."""

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

from rtsp_viewer.core.config import CameraConfig
from rtsp_viewer.utils.logger import get_logger

log = get_logger("unified_stream")


@dataclass
class StreamStats:
    """Stream statistics."""

    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    is_connected: bool = False
    is_recording: bool = False
    frames_received: int = 0
    frames_dropped: int = 0
    latency_ms: float = 0.0


class UnifiedStream:
    """
    Unified stream manager using OpenCV for display and ffmpeg for recording.

    Connections:
    - 1x OpenCV (display) - always active when streaming
    - 1x ffmpeg (recording) - only when recording
    - 1x ffplay (audio) - only when audio enabled

    This reduces connections vs having separate components.
    """

    # Health check settings
    HEALTH_CHECK_INTERVAL = 5.0
    FRAME_TIMEOUT = 10.0
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_DELAY = 2.0
    SEGMENT_DURATION = 30 * 60  # 30 minutes

    def __init__(self, camera: CameraConfig, output_dir: str | Path = "recordings"):
        self.camera = camera
        self.output_dir = Path(output_dir)

        # OpenCV capture for display
        self._cap: cv2.VideoCapture | None = None
        self._capture_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Frame data
        self._frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._frame_callbacks: list[Callable[[np.ndarray], None]] = []
        self._last_frame_time = 0.0

        # Recording (separate ffmpeg process)
        self._recording_process: subprocess.Popen | None = None
        self._recording_thread: threading.Thread | None = None
        self._recording_stop_event = threading.Event()
        self._is_recording = False
        self._session_dir: Path | None = None
        self._current_file: Path | None = None
        self._recording_start_time: datetime | None = None
        self._recorded_files: list[Path] = []
        self._record_audio = True

        # Audio (ffplay)
        self._audio_process: subprocess.Popen | None = None
        self._audio_enabled = False

        # Stats
        self._stats = StreamStats()
        self._reconnect_count = 0
        self._actual_fps = 0.0
        self._status_callback: Callable[[str], None] | None = None

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        """Set status update callback."""
        self._status_callback = callback

    def _notify_status(self, status: str) -> None:
        """Send status update."""
        if self._status_callback:
            try:
                self._status_callback(status)
            except Exception:
                pass

    def add_frame_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Add frame callback."""
        self._frame_callbacks.append(callback)

    def remove_frame_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Remove frame callback."""
        if callback in self._frame_callbacks:
            self._frame_callbacks.remove(callback)

    @property
    def stats(self) -> StreamStats:
        """Get stream stats."""
        return self._stats

    def get_frame(self) -> np.ndarray | None:
        """Get latest frame."""
        with self._frame_lock:
            return self._frame

    def is_streaming(self) -> bool:
        """Check if streaming."""
        return (
            self._capture_thread is not None
            and self._capture_thread.is_alive()
            and self._stats.is_connected
        )

    def is_recording(self) -> bool:
        """Check if recording."""
        return self._is_recording

    def _connect(self) -> bool:
        """Connect using OpenCV."""
        log.info(f"Connecting to {self.camera.name} at {self.camera.address}:{self.camera.port}")

        if self._cap is not None:
            self._cap.release()
            self._cap = None

        # Set FFmpeg options
        low_latency = self.camera.low_latency
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

        self._cap = cv2.VideoCapture(self.camera.rtsp_url, cv2.CAP_FFMPEG)

        if not self._cap.isOpened():
            log.error(f"Failed to open stream: {self.camera.name}")
            self._stats.is_connected = False
            return False

        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Get stream info
        self._stats.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._stats.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._stats.fps = self._cap.get(cv2.CAP_PROP_FPS)

        fourcc = int(self._cap.get(cv2.CAP_PROP_FOURCC))
        if fourcc > 0:
            self._stats.codec = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])

        self._stats.is_connected = True
        self._last_frame_time = time.time()

        log.info(
            f"Connected: {self._stats.width}x{self._stats.height} "
            f"@ {self._stats.fps:.1f}fps ({self._stats.codec})"
        )
        return True

    def _reconnect(self) -> bool:
        """Reconnect the stream."""
        self._reconnect_count += 1
        log.warning(f"Reconnecting ({self._reconnect_count}/{self.MAX_RECONNECT_ATTEMPTS})...")
        self._notify_status(f"Reconnecting ({self._reconnect_count}/{self.MAX_RECONNECT_ATTEMPTS})...")

        if self._reconnect_count > self.MAX_RECONNECT_ATTEMPTS:
            log.error("Max reconnect attempts reached")
            self._notify_status("Connection failed")
            return False

        time.sleep(self.RECONNECT_DELAY)

        if self._stop_event.is_set():
            return False

        if self._connect():
            self._reconnect_count = 0
            log.info("Reconnected successfully")
            self._notify_status("Reconnected")
            return True

        return False

    def start(self, enable_audio: bool = True) -> bool:
        """Start the stream."""
        if self.is_streaming():
            return True

        self._stop_event.clear()
        self._reconnect_count = 0
        self._audio_enabled = enable_audio
        self._stats.frames_received = 0
        self._stats.frames_dropped = 0

        self._notify_status("Connecting...")
        log.info(f"Starting stream: {self.camera.name}")

        if not self._connect():
            self._notify_status("Failed to connect")
            return False

        self._notify_status("Streaming")

        # Start capture thread
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        # Start audio if enabled
        if enable_audio:
            self._start_audio()

        log.info("Stream started")
        return True

    def _capture_loop(self) -> None:
        """Capture loop using OpenCV."""
        fps_start = time.time()
        frame_count = 0
        last_health_check = time.time()
        consecutive_failures = 0
        max_consecutive_failures = 30
        low_latency = self.camera.low_latency

        log.debug("Capture loop started")

        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._stats.is_connected = False
                if not self._reconnect():
                    break
                consecutive_failures = 0
                continue

            current_time = time.time()
            frame_start = current_time

            # Health check
            if current_time - last_health_check >= self.HEALTH_CHECK_INTERVAL:
                last_health_check = current_time
                if current_time - self._last_frame_time > self.FRAME_TIMEOUT:
                    log.warning("Stream timeout, reconnecting...")
                    self._notify_status("Stream timeout - reconnecting...")
                    self._stats.is_connected = False
                    if not self._reconnect():
                        break
                    consecutive_failures = 0
                    continue

            # Read frame
            if low_latency:
                # Drain buffer, keep only latest
                grabbed = False
                for _ in range(3):
                    if self._cap.grab():
                        grabbed = True
                    else:
                        break

                if not grabbed:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        log.warning("Stream stalled, reconnecting...")
                        self._notify_status("Stream stalled - reconnecting...")
                        self._stats.is_connected = False
                        if not self._reconnect():
                            break
                        consecutive_failures = 0
                    else:
                        time.sleep(0.01)
                    continue

                ret, frame = self._cap.retrieve()
            else:
                ret, frame = self._cap.read()

            if not ret or frame is None:
                self._stats.frames_dropped += 1
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    log.warning("Too many frame failures, reconnecting...")
                    self._notify_status("Stream stalled - reconnecting...")
                    self._stats.is_connected = False
                    if not self._reconnect():
                        break
                    consecutive_failures = 0
                continue

            consecutive_failures = 0
            current_time = time.time()
            decode_time = current_time - frame_start
            self._last_frame_time = current_time
            self._stats.frames_received += 1
            self._stats.latency_ms = decode_time * 1000
            frame_count += 1

            # Update FPS
            elapsed = current_time - fps_start
            if elapsed >= 1.0:
                self._stats.fps = frame_count / elapsed
                frame_count = 0
                fps_start = time.time()

            # Store frame
            with self._frame_lock:
                self._frame = frame

            # Callbacks
            for cb in self._frame_callbacks:
                try:
                    cb(frame)
                except Exception:
                    pass

        self._stats.is_connected = False
        log.debug("Capture loop ended")

    # --- Audio ---

    def _start_audio(self) -> None:
        """Start audio playback via ffplay."""
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
            log.info("Audio started")
        except Exception as e:
            log.error(f"Audio failed: {e}")

    def _stop_audio(self) -> None:
        """Stop audio."""
        if self._audio_process:
            try:
                self._audio_process.terminate()
                self._audio_process.wait(timeout=2.0)
            except Exception:
                try:
                    self._audio_process.kill()
                except Exception:
                    pass
            self._audio_process = None
            log.info("Audio stopped")

    def enable_audio(self) -> None:
        """Enable audio."""
        self._audio_enabled = True
        if self.is_streaming() and self._audio_process is None:
            self._start_audio()

    def disable_audio(self) -> None:
        """Disable audio."""
        self._audio_enabled = False
        self._stop_audio()

    # --- Recording ---

    def start_recording(self, record_audio: bool = True) -> bool:
        """Start recording."""
        if self._is_recording:
            return True

        if not self.is_streaming():
            log.error("Cannot record: not streaming")
            return False

        self._record_audio = record_audio
        self._recording_stop_event.clear()

        # Create session directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.camera.name)
        self._session_dir = self.output_dir / f"{safe_name}_{timestamp}"
        self._session_dir.mkdir(parents=True, exist_ok=True)

        self._recording_start_time = datetime.now()
        self._recorded_files = []
        self._is_recording = True
        self._stats.is_recording = True

        # Start recording thread
        self._recording_thread = threading.Thread(target=self._recording_loop, daemon=True)
        self._recording_thread.start()

        log.info(f"Recording started: {self._session_dir}")
        return True

    def _recording_loop(self) -> None:
        """Recording loop with segment rotation."""
        segment_num = 0
        consecutive_failures = 0
        max_failures = 5
        retry_delay = 5.0

        log.info(f"Recording loop started, segment duration: {self.SEGMENT_DURATION}s")

        while self._is_recording and not self._recording_stop_event.is_set():
            segment_num += 1

            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.camera.name)
            self._current_file = self._session_dir / f"{safe_name}_{timestamp}.mp4"

            log.info(f"Starting segment {segment_num}: {self._current_file.name}")

            # Build ffmpeg command
            cmd = [
                "ffmpeg",
                "-y",
                "-rtsp_transport", "tcp",
                "-fflags", "+genpts+discardcorrupt",
                "-buffer_size", "8192000",
                "-use_wallclock_as_timestamps", "1",
                "-i", self.camera.rtsp_url,
                "-c:v", "copy",
                "-reset_timestamps", "1",
            ]

            if self._record_audio:
                cmd.extend(["-c:a", "aac", "-b:a", "128k"])
            else:
                cmd.extend(["-an"])

            cmd.extend([
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                str(self._current_file),
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

                stderr_thread = threading.Thread(
                    target=drain, args=(self._recording_process, stderr_lines), daemon=True
                )
                stderr_thread.start()

                # Wait for segment duration
                segment_start = time.time()
                segment_failed = False

                while self._is_recording and not self._recording_stop_event.is_set():
                    exit_code = self._recording_process.poll()
                    if exit_code is not None:
                        elapsed = time.time() - segment_start
                        if exit_code != 0 or elapsed < 5.0:
                            log.error(f"FFmpeg exited with {exit_code} after {elapsed:.1f}s")
                            stderr_thread.join(timeout=1.0)
                            for line in stderr_lines[-10:]:
                                log.error(f"  ffmpeg: {line}")
                            segment_failed = True
                        break

                    elapsed = time.time() - segment_start
                    if elapsed >= self.SEGMENT_DURATION:
                        log.info(f"Segment {segment_num} complete, rotating...")
                        break

                    self._recording_stop_event.wait(0.5)

                # Graceful stop
                self._stop_recording_process()
                stderr_thread.join(timeout=2.0)

                if segment_failed:
                    consecutive_failures += 1
                    log.warning(f"Segment failed ({consecutive_failures}/{max_failures})")
                    if consecutive_failures >= max_failures:
                        log.error("Too many recording failures, stopping")
                        break
                    log.info(f"Retrying in {retry_delay}s...")
                    if self._recording_stop_event.wait(retry_delay):
                        break
                    continue

                consecutive_failures = 0

                # Track file
                if self._current_file and self._current_file.exists():
                    size = self._current_file.stat().st_size
                    if size > 0:
                        self._recorded_files.append(self._current_file)
                        log.info(f"Segment {segment_num} saved: {self._current_file} ({size / 1024 / 1024:.2f} MB)")
                    else:
                        log.warning(f"Segment {segment_num} is empty: {self._current_file}")
                else:
                    log.warning(f"Segment {segment_num} file not found: {self._current_file}")

            except Exception as e:
                log.exception(f"Recording error: {e}")
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    break
                if self._recording_stop_event.wait(retry_delay):
                    break

        self._is_recording = False
        self._stats.is_recording = False
        log.info(f"Recording stopped. Segments: {len(self._recorded_files)}")

    def _stop_recording_process(self) -> None:
        """Gracefully stop recording ffmpeg."""
        proc = self._recording_process
        self._recording_process = None

        if proc is None:
            return

        if proc.poll() is not None:
            log.debug(f"Recording ffmpeg already exited with {proc.returncode}")
            return

        log.debug("Sending 'q' to recording ffmpeg...")
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
        except Exception as e:
            log.debug(f"Could not send quit: {e}")

        try:
            proc.wait(timeout=5.0)
            log.debug(f"Recording ffmpeg exited with {proc.returncode}")
        except subprocess.TimeoutExpired:
            log.warning("Recording ffmpeg not responding, terminating...")
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                log.warning("Killing recording ffmpeg...")
                proc.kill()

    def stop_recording(self) -> Path | None:
        """Stop recording."""
        if not self._is_recording:
            return None

        log.info("Stopping recording...")
        self._recording_stop_event.set()
        self._is_recording = False

        if self._recording_thread:
            self._recording_thread.join(timeout=10.0)
            self._recording_thread = None

        session = self._session_dir
        self._session_dir = None
        self._recording_start_time = None

        return session

    def get_recording_duration(self) -> float:
        """Get recording duration."""
        if self._recording_start_time and self._is_recording:
            return (datetime.now() - self._recording_start_time).total_seconds()
        return 0.0

    def get_recorded_files(self) -> list[Path]:
        """Get recorded files."""
        return self._recorded_files.copy()

    # --- Stop ---

    def stop(self) -> None:
        """Stop everything."""
        log.info("Stopping unified stream...")

        self._stop_event.set()

        # Stop recording
        if self._is_recording:
            self.stop_recording()

        # Stop audio
        self._stop_audio()

        # Stop capture
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None

        # Cleanup environment
        if "OPENCV_FFMPEG_CAPTURE_OPTIONS" in os.environ:
            del os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]

        self._stats.is_connected = False
        self._frame = None

        log.info("Unified stream stopped")
