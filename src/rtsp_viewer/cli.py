#!/usr/bin/env python3
"""RTSP Stream Viewer and Recorder - CLI Entry Point."""

import argparse
import shutil
import sys
from pathlib import Path


def check_dependencies() -> list[str]:
    """Check if required dependencies are available."""
    missing = []

    # Check Python packages
    try:
        import cv2  # noqa: F401
    except ImportError:
        missing.append("opencv-python")

    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")

    try:
        import yaml  # noqa: F401
    except ImportError:
        missing.append("pyyaml")

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("pillow")

    # Check system dependencies
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg (system)")

    if not shutil.which("ffplay"):
        missing.append("ffplay (system - usually comes with ffmpeg)")

    return missing


def main() -> int:
    """Main entry point for the RTSP viewer application."""
    parser = argparse.ArgumentParser(
        description="RTSP Stream Viewer and Recorder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                      # Start with default config (cameras.yaml)
  %(prog)s -c my_cameras.yaml   # Use custom config file
  %(prog)s --check              # Check dependencies only

Keyboard shortcuts:
  Space     Toggle play/pause
  R         Toggle recording
  Escape    Exit application
        """,
    )

    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("cameras.yaml"),
        help="Path to camera configuration file (default: cameras.yaml)",
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Check dependencies and exit",
    )

    args = parser.parse_args()

    # Check dependencies
    missing = check_dependencies()
    if missing:
        print("Missing dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print()
        if "ffmpeg" in str(missing) or "ffplay" in str(missing):
            print("Install ffmpeg:")
            print("  macOS:   brew install ffmpeg")
            print("  Ubuntu:  sudo apt install ffmpeg")
            print("  Windows: choco install ffmpeg")
            print()
        python_deps = [d for d in missing if "(system)" not in d]
        if python_deps:
            print("Install Python packages:")
            print(f"  pip install {' '.join(python_deps)}")
        return 1

    if args.check:
        print("All dependencies are installed!")
        return 0

    # Check config file exists
    if not args.config.exists():
        print(f"Configuration file not found: {args.config}")
        print()
        print("Create a cameras.yaml file with your camera settings.")
        print("Example:")
        print("""
cameras:
  - name: "My Camera"
    address: "192.168.1.100"
    port: 554
    username: "admin"
    password: "password"
    path: ""
        """)
        return 1

    # Import and run the GUI
    from rtsp_viewer.core import RTSPViewer
    from rtsp_viewer.ui import ViewerGUI

    print("Starting RTSP Viewer...")
    viewer = RTSPViewer(config_path=args.config)
    gui = ViewerGUI(viewer)
    gui.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
