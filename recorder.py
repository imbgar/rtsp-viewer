"""Recording functionality using ffmpeg for highest quality capture."""

import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from config import CameraConfig
from logger import get_logger

log = get_logger("recorder")

# Default segment duration in seconds (30 minutes)
DEFAULT_SEGMENT_DURATION = 30 * 60


class Recorder:
    """Records RTSP streams using ffmpeg at the highest available quality."""

    def __init__(
        self,
        camera: CameraConfig,
        output_dir: str | Path = "recordings",
        segment_duration: int = DEFAULT_SEGMENT_DURATION,
    ):
        self.camera = camera
        self.output_dir = Path(output_dir)
        self.segment_duration = segment_duration
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_recording = False
        self._current_file: Path | None = None
        self._start_time: datetime | None = None
        self._segment_start_time: datetime | None = None
        self._record_audio = True
        self._recorded_files: list[Path] = []
        self._session_dir: Path | None = None

    @staticmethod
    def is_available() -> bool:
        """Check if ffmpeg is available on the system."""
        return shutil.which("ffmpeg") is not None

    def _create_session_dir(self) -> Path:
        """Create a session directory for this recording session."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in self.camera.name
        )
        session_dir = self.output_dir / f"{safe_name}_{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=True)

        return session_dir

    def _generate_filename(self) -> Path:
        """Generate a timestamped filename for the recording."""
        if self._session_dir is None:
            self._session_dir = self._create_session_dir()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in self.camera.name
        )
        filename = f"{safe_name}_{timestamp}.mp4"

        return self._session_dir / filename

    def start(self, record_audio: bool = True) -> bool:
        """Start recording the stream."""
        if not self.is_available():
            print("Error: ffmpeg not found. Recording disabled.")
            return False

        if self._is_recording:
            return True

        self._stop_event.clear()
        self._record_audio = record_audio
        self._start_time = datetime.now()
        self._recorded_files = []

        # Create session directory for this recording session
        self._session_dir = self._create_session_dir()

        # Set recording flag before starting thread to avoid race condition
        self._is_recording = True

        # Start recording in a separate thread
        self._thread = threading.Thread(target=self._recording_loop, daemon=True)
        self._thread.start()

        return True

    def _build_ffmpeg_command(self, output_file: Path) -> list[str]:
        """Build the ffmpeg command for recording."""
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-use_wallclock_as_timestamps", "1",  # Use system clock for timestamps
            "-fflags", "+genpts+discardcorrupt",  # Generate PTS and discard corrupt frames
            "-rtsp_transport", "tcp",  # Use TCP transport
            "-buffer_size", "8192000",  # 8MB buffer for high-bitrate 2K streams
            "-probesize", "10000000",  # 10MB probe size for faster stream analysis
            "-analyzeduration", "10000000",  # 10 seconds analysis duration
            "-i", self.camera.rtsp_url,
            "-c:v", "copy",  # Copy video without re-encoding
            "-reset_timestamps", "1",  # Reset timestamps at start
        ]

        if self._record_audio:
            # Re-encode audio to AAC (pcm_alaw/mulaw from some cameras isn't MP4 compatible)
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            # No audio
            cmd.extend(["-an"])

        cmd.extend([
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof",  # Fragmented MP4 - writes moov at start, survives crashes
            str(output_file),
        ])

        return cmd

    def _recording_loop(self) -> None:
        """Run ffmpeg for recording with segment rotation."""
        log.info(f"Recording started for camera: {self.camera.name}")
        log.info(f"Session directory: {self._session_dir}")
        log.info(f"Segment duration: {self.segment_duration}s")

        segment_number = 0
        consecutive_failures = 0
        max_consecutive_failures = 5
        retry_delay = 5.0  # seconds between retries

        while not self._stop_event.is_set() and self._is_recording:
            segment_number += 1
            self._current_file = self._generate_filename()
            self._segment_start_time = datetime.now()

            log.info(f"Starting segment {segment_number}: {self._current_file.name}")

            cmd = self._build_ffmpeg_command(self._current_file)
            log.debug(f"FFmpeg command: {' '.join(cmd)}")

            stderr_lines: list[str] = []

            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )

                # Drain stderr in background and collect output for debugging
                def drain_stderr(proc: subprocess.Popen, lines: list[str]) -> None:
                    try:
                        if proc.stderr:
                            for line in proc.stderr:
                                decoded = line.decode("utf-8", errors="replace").strip()
                                if decoded:
                                    lines.append(decoded)
                    except Exception:
                        pass

                stderr_thread = threading.Thread(
                    target=drain_stderr,
                    args=(self._process, stderr_lines),
                    daemon=True,
                )
                stderr_thread.start()

                # Wait for segment duration or stop event
                segment_start = time.time()
                segment_failed = False

                while not self._stop_event.is_set():
                    exit_code = self._process.poll()
                    if exit_code is not None:
                        # Process ended - check if it was an error
                        elapsed = time.time() - segment_start
                        if exit_code != 0 or elapsed < 5.0:
                            # Failed or exited too quickly
                            log.error(f"FFmpeg exited with code {exit_code} after {elapsed:.1f}s")
                            stderr_thread.join(timeout=1.0)
                            for line in stderr_lines[-10:]:
                                log.error(f"  ffmpeg: {line}")
                            segment_failed = True
                        break

                    # Check if segment duration reached
                    elapsed = time.time() - segment_start
                    if elapsed >= self.segment_duration:
                        log.info(f"Segment {segment_number} reached duration limit, rotating...")
                        break

                    self._stop_event.wait(0.5)

                # Gracefully stop current segment
                self._graceful_stop()

                # Wait for stderr thread to finish
                stderr_thread.join(timeout=2.0)

                # Handle segment failure with retry logic
                if segment_failed:
                    consecutive_failures += 1
                    log.warning(
                        f"Segment failed ({consecutive_failures}/{max_consecutive_failures})"
                    )

                    if consecutive_failures >= max_consecutive_failures:
                        log.error("Too many consecutive failures, stopping recording")
                        break

                    # Wait before retrying
                    log.info(f"Waiting {retry_delay}s before retry...")
                    if self._stop_event.wait(retry_delay):
                        break  # Stop event was set
                    continue  # Try again without incrementing segment number

                # Reset failure counter on success
                consecutive_failures = 0

                # Track recorded file if it exists and has content
                if self._current_file and self._current_file.exists():
                    file_size = self._current_file.stat().st_size
                    if file_size > 0:
                        self._recorded_files.append(self._current_file)
                        log.info(f"Segment {segment_number} saved: {file_size / 1024 / 1024:.2f} MB")
                    else:
                        log.warning(f"Segment {segment_number} is empty (0 bytes)")
                else:
                    log.warning(f"Segment {segment_number} file not found")

            except Exception as e:
                log.exception(f"Recording error: {e}")
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    break
                log.info(f"Waiting {retry_delay}s before retry...")
                if self._stop_event.wait(retry_delay):
                    break

        self._is_recording = False
        log.info(f"Recording stopped. Total segments: {len(self._recorded_files)}")

    def _graceful_stop(self) -> None:
        """Gracefully stop ffmpeg to ensure file is properly finalized."""
        if self._process is None:
            return

        proc = self._process
        self._process = None

        # Check if process is already dead
        if proc.poll() is not None:
            log.debug(f"FFmpeg already exited with code {proc.returncode}")
            return

        # Send 'q' to ffmpeg for graceful shutdown
        log.debug("Sending 'q' to ffmpeg for graceful shutdown...")
        try:
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError) as e:
            log.debug(f"Could not send quit signal (process may have exited): {e}")

        # Wait for process to finish
        try:
            proc.wait(timeout=5.0)
            log.debug(f"FFmpeg exited gracefully with code {proc.returncode}")
        except subprocess.TimeoutExpired:
            log.warning("FFmpeg did not respond to quit, sending SIGTERM...")
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
                log.debug("FFmpeg terminated")
            except subprocess.TimeoutExpired:
                log.warning("FFmpeg did not respond to SIGTERM, sending SIGKILL...")
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                    log.debug("FFmpeg killed")
                except Exception as e:
                    log.error(f"Failed to kill ffmpeg: {e}")
            except Exception as e:
                log.error(f"Error terminating ffmpeg: {e}")
        except Exception as e:
            log.error(f"Error waiting for ffmpeg: {e}")

    def stop(self) -> Path | None:
        """Stop recording and return the path to the session directory."""
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None

        self._is_recording = False

        # Track the last recorded file
        last_file = self._current_file
        if last_file and last_file.exists() and last_file.stat().st_size > 0:
            if last_file not in self._recorded_files:
                self._recorded_files.append(last_file)

        # Return the session directory (contains all segment files)
        session_dir = self._session_dir

        self._current_file = None
        self._start_time = None
        self._segment_start_time = None
        self._session_dir = None

        return session_dir

    def get_recorded_files(self) -> list[Path]:
        """Get list of all recorded files from this session."""
        return self._recorded_files.copy()

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_recording

    def get_current_file(self) -> Path | None:
        """Get the path to the current recording file."""
        return self._current_file

    def get_session_dir(self) -> Path | None:
        """Get the path to the current session directory."""
        return self._session_dir

    def get_recording_duration(self) -> float:
        """Get the total duration of the current recording session in seconds."""
        if self._start_time is None:
            return 0.0
        return (datetime.now() - self._start_time).total_seconds()

    def get_segment_duration(self) -> float:
        """Get the duration of the current segment in seconds."""
        if self._segment_start_time is None:
            return 0.0
        return (datetime.now() - self._segment_start_time).total_seconds()


class StreamProbe:
    """Probe RTSP stream to get detailed information."""

    @staticmethod
    def get_stream_info(rtsp_url: str) -> dict:
        """
        Get detailed stream information using ffprobe.

        Returns dict with keys: width, height, fps, video_codec, audio_codec, bitrate
        """
        if not shutil.which("ffprobe"):
            return {}

        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            "-rtsp_transport", "tcp",
            rtsp_url,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return {}

            import json

            data = json.loads(result.stdout)

            info = {
                "width": 0,
                "height": 0,
                "fps": 0.0,
                "video_codec": "",
                "audio_codec": "",
                "bitrate": 0,
            }

            # Parse streams
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    info["width"] = stream.get("width", 0)
                    info["height"] = stream.get("height", 0)
                    info["video_codec"] = stream.get("codec_name", "")

                    # Parse frame rate
                    fps_str = stream.get("r_frame_rate", "0/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        if int(den) > 0:
                            info["fps"] = int(num) / int(den)

                elif stream.get("codec_type") == "audio":
                    info["audio_codec"] = stream.get("codec_name", "")

            # Parse format for bitrate
            fmt = data.get("format", {})
            if "bit_rate" in fmt:
                info["bitrate"] = int(fmt["bit_rate"])

            return info

        except Exception:
            return {}
