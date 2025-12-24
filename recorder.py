"""Recording functionality using ffmpeg for highest quality capture."""

import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from config import CameraConfig

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

    @staticmethod
    def is_available() -> bool:
        """Check if ffmpeg is available on the system."""
        return shutil.which("ffmpeg") is not None

    def _generate_filename(self) -> Path:
        """Generate a timestamped filename for the recording."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in self.camera.name
        )
        filename = f"{safe_name}_{timestamp}.mp4"

        return self.output_dir / filename

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
            "-rtsp_transport", "tcp",  # Use TCP transport
            "-i", self.camera.rtsp_url,
            "-c:v", "copy",  # Copy video without re-encoding
        ]

        if self._record_audio:
            # Re-encode audio to AAC (pcm_alaw/mulaw from some cameras isn't MP4 compatible)
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            # No audio
            cmd.extend(["-an"])

        cmd.extend([
            "-movflags", "+faststart",  # Optimize for streaming
            str(output_file),
        ])

        return cmd

    def _recording_loop(self) -> None:
        """Run ffmpeg for recording with segment rotation."""
        while not self._stop_event.is_set() and self._is_recording:
            # Generate new filename for this segment
            self._current_file = self._generate_filename()
            self._segment_start_time = datetime.now()

            cmd = self._build_ffmpeg_command(self._current_file)

            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                # Wait for segment duration or stop event
                segment_start = time.time()
                while not self._stop_event.is_set():
                    if self._process.poll() is not None:
                        # Process ended unexpectedly
                        break

                    # Check if segment duration reached
                    elapsed = time.time() - segment_start
                    if elapsed >= self.segment_duration:
                        # Time to rotate to a new segment
                        break

                    self._stop_event.wait(0.5)

                # Gracefully stop current segment
                self._graceful_stop()

                # Track recorded file if it exists and has content
                if self._current_file and self._current_file.exists():
                    if self._current_file.stat().st_size > 0:
                        self._recorded_files.append(self._current_file)

            except Exception as e:
                print(f"Recording error: {e}")
                break

        self._is_recording = False

    def _graceful_stop(self) -> None:
        """Gracefully stop ffmpeg to ensure file is properly finalized."""
        if self._process is None:
            return

        proc = self._process
        self._process = None

        # Send 'q' to ffmpeg for graceful shutdown
        try:
            if proc.stdin is not None:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            # Process already terminated or pipe closed
            pass

        # Wait for process to finish
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def stop(self) -> Path | None:
        """Stop recording and return the path to the last recorded file."""
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None

        self._is_recording = False

        # Return the last recorded file
        last_file = self._current_file
        if last_file and last_file.exists() and last_file.stat().st_size > 0:
            if last_file not in self._recorded_files:
                self._recorded_files.append(last_file)

        self._current_file = None
        self._start_time = None
        self._segment_start_time = None

        return last_file

    def get_recorded_files(self) -> list[Path]:
        """Get list of all recorded files from this session."""
        return self._recorded_files.copy()

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_recording

    def get_current_file(self) -> Path | None:
        """Get the path to the current recording file."""
        return self._current_file

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
