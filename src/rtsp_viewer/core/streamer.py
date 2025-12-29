"""RTSP streamer - serves a video file as a local RTSP stream."""

import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from rtsp_viewer.utils.logger import get_logger

log = get_logger("streamer")

DEFAULT_PORT = 8554


class RTSPStreamer:
    """
    Serves a video file as a local RTSP stream.

    Requires mediamtx (formerly rtsp-simple-server) to be installed:
        brew install mediamtx   # macOS
        # Or download from: https://github.com/bluenviron/mediamtx/releases

    Usage:
        streamer = RTSPStreamer("video.mp4")
        streamer.start()
        # Stream available at rtsp://localhost:8554/stream
        streamer.stop()

    Or as context manager:
        with RTSPStreamer("video.mp4") as s:
            print(f"Stream at: {s.rtsp_url}")
            # Do something with the stream
    """

    def __init__(
        self,
        video_path: str | Path,
        port: int = DEFAULT_PORT,
        stream_name: str = "stream",
        enable_audio: bool = True,
    ):
        self.video_path = Path(video_path)
        self.port = port
        self.stream_name = stream_name
        self.enable_audio = enable_audio
        self._server_process: subprocess.Popen | None = None
        self._ffmpeg_process: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        self._config_file = None
        self._running = False

    @property
    def rtsp_url(self) -> str:
        """Get the RTSP URL for the simulated stream."""
        return f"rtsp://localhost:{self.port}/{self.stream_name}"

    @staticmethod
    def check_dependencies() -> dict[str, bool]:
        """Check if required dependencies are available."""
        return {
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "mediamtx": shutil.which("mediamtx") is not None,
        }

    @staticmethod
    def is_available() -> bool:
        """Check if all dependencies are available."""
        deps = RTSPStreamer.check_dependencies()
        return all(deps.values())

    def start(self) -> bool:
        """Start the RTSP stream server."""
        deps = self.check_dependencies()

        if not deps["ffmpeg"]:
            log.error("ffmpeg not found. Install with: brew install ffmpeg")
            return False

        if not deps["mediamtx"]:
            log.error("mediamtx not found. Install with: brew install mediamtx")
            log.error("Or download from: https://github.com/bluenviron/mediamtx/releases")
            return False

        if not self.video_path.exists():
            log.error(f"Video file not found: {self.video_path}")
            return False

        if self._running:
            log.warning("Streamer already running")
            return True

        # Start mediamtx RTSP server
        if not self._start_server():
            return False

        # Give server time to start
        time.sleep(1.0)

        # Start ffmpeg to push stream to server
        if not self._start_stream():
            self._stop_server()
            return False

        self._running = True
        log.info(f"Streamer running - stream available at: {self.rtsp_url}")
        return True

    def _start_server(self) -> bool:
        """Start the mediamtx RTSP server."""
        import os
        import tempfile

        log.info(f"Starting RTSP server on port {self.port}...")

        # Create a minimal mediamtx config file that allows publishing
        config_content = f"""
logLevel: warn
protocols: [tcp]
rtspAddress: :{self.port}

paths:
  all:
    source: publisher
"""
        # Write config to temp file
        self._config_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yml', delete=False
        )
        self._config_file.write(config_content)
        self._config_file.close()

        try:
            self._server_process = subprocess.Popen(
                ["mediamtx", self._config_file.name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            # Start thread to drain server stderr
            threading.Thread(
                target=self._drain_process_stderr,
                args=(self._server_process, "mediamtx"),
                daemon=True,
            ).start()

            log.info("RTSP server started")
            return True

        except Exception as e:
            log.exception(f"Failed to start RTSP server: {e}")
            return False

    def _start_stream(self) -> bool:
        """Start ffmpeg to stream video to the server."""
        log.info(f"Starting video stream: {self.video_path.name} (audio: {self.enable_audio})")

        # Build ffmpeg command for stable RTSP streaming
        # Key: use -re for real-time, copy codecs, and proper RTSP settings
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-re",  # Read at native frame rate
            "-fflags", "+genpts",  # Generate presentation timestamps
            "-stream_loop", "-1",  # Loop infinitely
            "-i", str(self.video_path),
            # Copy video - no re-encoding
            "-c:v", "copy",
        ]

        # Audio options
        if self.enable_audio:
            cmd.extend(["-c:a", "copy"])  # Try copy first for lowest latency
        else:
            cmd.extend(["-an"])

        cmd.extend([
            # RTSP output settings
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            "-muxdelay", "0.1",  # Low mux delay
            self.rtsp_url,
        ])

        log.debug(f"FFmpeg command: {' '.join(cmd)}")

        try:
            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            # Start thread to drain ffmpeg stderr
            self._stderr_thread = threading.Thread(
                target=self._drain_process_stderr,
                args=(self._ffmpeg_process, "ffmpeg"),
                daemon=True,
            )
            self._stderr_thread.start()

            # Wait a moment and check if process is still running
            time.sleep(0.5)
            if self._ffmpeg_process.poll() is not None:
                log.error("FFmpeg exited immediately")
                return False

            log.info("Video stream started")
            return True

        except Exception as e:
            log.exception(f"Failed to start video stream: {e}")
            return False

    def _drain_process_stderr(self, process: subprocess.Popen, name: str) -> None:
        """Drain stderr from a process."""
        if process.stderr is None:
            return

        # Patterns to skip (noisy but not useful)
        skip_patterns = (
            "frame=",
            "size=",
            "Resumed reading",  # Normal real-time streaming behavior
            "fps=",
            "bitrate=",
        )

        try:
            for line in process.stderr:
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    # Skip noisy progress/info lines
                    if name == "ffmpeg" and any(p in decoded for p in skip_patterns):
                        continue
                    if "error" in decoded.lower():
                        log.error(f"{name}: {decoded}")
                    elif "warning" in decoded.lower():
                        log.warning(f"{name}: {decoded}")
                    else:
                        log.debug(f"{name}: {decoded}")
        except Exception:
            pass

    def _stop_server(self) -> None:
        """Stop the RTSP server."""
        import os

        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
                self._server_process.wait(timeout=1.0)
            except Exception as e:
                log.error(f"Error stopping server: {e}")
            finally:
                self._server_process = None

        # Clean up config file
        if self._config_file is not None:
            try:
                os.unlink(self._config_file.name)
            except Exception:
                pass
            self._config_file = None

    def _stop_stream(self) -> None:
        """Stop the ffmpeg stream."""
        if self._ffmpeg_process is not None:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._ffmpeg_process.kill()
                self._ffmpeg_process.wait(timeout=1.0)
            except Exception as e:
                log.error(f"Error stopping stream: {e}")
            finally:
                self._ffmpeg_process = None

    def stop(self) -> None:
        """Stop the streamer."""
        if not self._running:
            return

        log.info("Stopping streamer...")
        self._running = False

        self._stop_stream()
        self._stop_server()

        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=2.0)
            self._stderr_thread = None

        log.info("Streamer stopped")

    def is_running(self) -> bool:
        """Check if the streamer is running."""
        if not self._running:
            return False
        if self._ffmpeg_process is None or self._server_process is None:
            return False
        return (
            self._ffmpeg_process.poll() is None
            and self._server_process.poll() is None
        )

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False


def run_streamer_cli():
    """CLI entry point for running the streamer standalone."""
    import argparse

    parser = argparse.ArgumentParser(
        description="RTSP Streamer - Serve a video file as an RTSP stream",
    )
    parser.add_argument(
        "video",
        type=Path,
        help="Path to video file to stream",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"RTSP server port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "-n", "--name",
        default="stream",
        help="Stream name (default: stream)",
    )

    args = parser.parse_args()

    # Check dependencies
    deps = RTSPStreamer.check_dependencies()
    missing = [k for k, v in deps.items() if not v]
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("\nInstall with:")
        print("  brew install ffmpeg mediamtx")
        sys.exit(1)

    streamer = RTSPStreamer(
        video_path=args.video,
        port=args.port,
        stream_name=args.name,
    )

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nStopping...")
        streamer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not streamer.start():
        sys.exit(1)

    print(f"\nRTSP stream available at: {streamer.rtsp_url}")
    print("Press Ctrl+C to stop\n")

    # Keep running until interrupted
    try:
        while streamer.is_running():
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        streamer.stop()


if __name__ == "__main__":
    run_streamer_cli()
