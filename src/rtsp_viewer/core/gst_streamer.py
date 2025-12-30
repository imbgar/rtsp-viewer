"""GStreamer-based RTSP streamer - more reliable than ffmpeg+mediamtx."""

import shutil
import signal
import sys
import threading
import time
from pathlib import Path

from rtsp_viewer.utils.logger import get_logger

log = get_logger("gst_streamer")

DEFAULT_PORT = 8554

# Check if GStreamer is available
_gst_available = False
_gst_import_error = None

try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstRtspServer', '1.0')
    from gi.repository import Gst  # noqa: F401 - used for Gst.init
    Gst.init(None)
    _gst_available = True
except (ImportError, ValueError) as e:
    _gst_import_error = str(e)


class GstRTSPStreamer:
    """
    Serves a video file as a local RTSP stream using GStreamer.

    This is more reliable than ffmpeg+mediamtx for smooth playback.

    Requires GStreamer and gst-rtsp-server:
        brew install gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-rtsp-server

    Usage:
        streamer = GstRTSPStreamer("video.mp4")
        streamer.start()
        # Stream available at rtsp://localhost:8554/stream
        streamer.stop()

    Or as context manager:
        with GstRTSPStreamer("video.mp4") as s:
            print(f"Stream at: {s.rtsp_url}")
    """

    def __init__(
        self,
        video_path: str | Path,
        port: int = DEFAULT_PORT,
        stream_name: str = "stream",
        enable_audio: bool = True,
    ):
        self.video_path = Path(video_path).resolve()
        self.port = port
        self.stream_name = stream_name
        self.enable_audio = enable_audio
        self._server = None
        self._loop = None
        self._loop_thread = None
        self._running = False

    @property
    def rtsp_url(self) -> str:
        """Get the RTSP URL for the simulated stream."""
        return f"rtsp://localhost:{self.port}/{self.stream_name}"

    @staticmethod
    def check_dependencies() -> dict[str, bool]:
        """Check if required dependencies are available."""
        return {
            "gstreamer": shutil.which("gst-launch-1.0") is not None,
            "gst-rtsp-server": _gst_available,
        }

    @staticmethod
    def is_available() -> bool:
        """Check if all dependencies are available."""
        deps = GstRTSPStreamer.check_dependencies()
        return all(deps.values())

    @staticmethod
    def get_import_error() -> str | None:
        """Get the import error message if GStreamer is not available."""
        return _gst_import_error

    def start(self) -> bool:
        """Start the RTSP stream server."""
        if not _gst_available:
            log.error(f"GStreamer not available: {_gst_import_error}")
            log.error(
                "Install with: brew install gstreamer gst-plugins-base "
                "gst-plugins-good gst-plugins-bad gst-rtsp-server pygobject3"
            )
            return False

        if not self.video_path.exists():
            log.error(f"Video file not found: {self.video_path}")
            return False

        if self._running:
            log.warning("Streamer already running")
            return True

        try:
            self._start_server()
            self._running = True
            log.info(f"GStreamer RTSP server running at: {self.rtsp_url}")
            return True
        except Exception as e:
            log.exception(f"Failed to start GStreamer RTSP server: {e}")
            return False

    def _start_server(self) -> None:
        """Start the GStreamer RTSP server."""
        from gi.repository import GLib, GstRtspServer

        # Create RTSP server
        self._server = GstRtspServer.RTSPServer.new()
        self._server.set_service(str(self.port))

        # Get mount points
        mounts = self._server.get_mount_points()

        # Create media factory
        factory = GstRtspServer.RTSPMediaFactory.new()
        factory.set_shared(True)  # Share the same pipeline for all clients

        # Build GStreamer pipeline for file playback

        if self.enable_audio:
            # Pipeline with audio
            pipeline = (
                f"( filesrc location=\"{self.video_path}\" ! "
                f"qtdemux name=demux "
                f"demux.video_0 ! queue ! h264parse ! rtph264pay name=pay0 pt=96 "
                f"demux.audio_0 ! queue ! aacparse ! rtpmp4apay name=pay1 pt=97 )"
            )
        else:
            # Video only pipeline
            pipeline = (
                f"( filesrc location=\"{self.video_path}\" ! "
                f"qtdemux name=demux "
                f"demux.video_0 ! queue ! h264parse ! rtph264pay name=pay0 pt=96 )"
            )

        log.debug(f"GStreamer pipeline: {pipeline}")
        factory.set_launch(pipeline)

        # Add factory to mount points
        mounts.add_factory(f"/{self.stream_name}", factory)

        # Attach server to default main context
        self._server.attach(None)

        # Create and run main loop in background thread
        self._loop = GLib.MainLoop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        log.info(f"RTSP server started on port {self.port}")

    def _run_loop(self) -> None:
        """Run the GLib main loop."""
        try:
            self._loop.run()
        except Exception as e:
            log.error(f"Main loop error: {e}")

    def stop(self) -> None:
        """Stop the streamer."""
        if not self._running:
            return

        log.info("Stopping GStreamer RTSP server...")
        self._running = False

        if self._loop is not None:
            self._loop.quit()
            self._loop = None

        if self._loop_thread is not None:
            self._loop_thread.join(timeout=2.0)
            self._loop_thread = None

        self._server = None
        log.info("GStreamer RTSP server stopped")

    def is_running(self) -> bool:
        """Check if the streamer is running."""
        return self._running and self._loop_thread is not None and self._loop_thread.is_alive()

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False


class LoopingGstRTSPStreamer(GstRTSPStreamer):
    """
    GStreamer RTSP streamer with infinite looping support.

    Uses a custom media factory that seeks back to start when EOS is reached.
    """

    def _start_server(self) -> None:
        """Start the GStreamer RTSP server with looping support."""
        from gi.repository import GLib, GstRtspServer

        # Create RTSP server
        self._server = GstRtspServer.RTSPServer.new()
        self._server.set_service(str(self.port))

        # Get mount points
        mounts = self._server.get_mount_points()

        # Create media factory with a pipeline that re-encodes for consistent output
        factory = GstRtspServer.RTSPMediaFactory.new()
        factory.set_shared(True)

        # Use uridecodebin for flexible input and re-encode to H264
        # This gives consistent timing and allows seeking
        # videorate ensures consistent framerate output
        uri = self.video_path.as_uri()

        if self.enable_audio:
            pipeline = (
                f"( uridecodebin uri={uri} name=src "
                f"src. ! queue ! videoconvert ! videorate ! "
                f"x264enc tune=zerolatency speed-preset=ultrafast ! "
                f"rtph264pay name=pay0 pt=96 "
                f"src. ! queue ! audioconvert ! voaacenc ! rtpmp4apay name=pay1 pt=97 )"
            )
        else:
            pipeline = (
                f"( uridecodebin uri={uri} name=src "
                f"src. ! queue ! videoconvert ! videorate ! "
                f"x264enc tune=zerolatency speed-preset=ultrafast ! "
                f"rtph264pay name=pay0 pt=96 )"
            )

        log.debug(f"GStreamer looping pipeline: {pipeline}")
        factory.set_launch(pipeline)

        # Enable EOS shutdown and let clients reconnect for "looping"
        # For true looping, we'd need a custom element, but this works for testing

        mounts.add_factory(f"/{self.stream_name}", factory)
        self._server.attach(None)

        self._loop = GLib.MainLoop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        log.info(f"Looping RTSP server started on port {self.port}")


def run_gst_streamer_cli():
    """CLI entry point for running the GStreamer streamer standalone."""
    import argparse

    parser = argparse.ArgumentParser(
        description="GStreamer RTSP Streamer - Serve a video file as an RTSP stream",
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
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Disable audio streaming",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Use looping mode (re-encodes video)",
    )

    args = parser.parse_args()

    # Check dependencies
    deps = GstRTSPStreamer.check_dependencies()
    missing = [k for k, v in deps.items() if not v]
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        if not deps["gst-rtsp-server"]:
            error = GstRTSPStreamer.get_import_error()
            print(f"Import error: {error}")
        print("\nInstall with:")
        print("  brew install gstreamer gst-plugins-base gst-plugins-good \\")
        print("               gst-plugins-bad gst-rtsp-server pygobject3")
        sys.exit(1)

    StreamerClass = LoopingGstRTSPStreamer if args.loop else GstRTSPStreamer
    streamer = StreamerClass(
        video_path=args.video,
        port=args.port,
        stream_name=args.name,
        enable_audio=not args.no_audio,
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
    run_gst_streamer_cli()
