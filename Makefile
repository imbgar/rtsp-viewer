.PHONY: install dev lint format typecheck test clean run check help install-ffmpeg install-tkinter install-mediamtx install-gstreamer install-system-deps stream stream-gst streamer-gui

# Detect OS
UNAME_S := $(shell uname -s)

# Default target
help:
	@echo "RTSP Viewer - Available targets:"
	@echo ""
	@echo "  install             Install Python dependencies"
	@echo "  dev                 Install development dependencies"
	@echo "  install-system-deps Install system dependencies (ffmpeg, tkinter)"
	@echo "  install-ffmpeg      Install ffmpeg"
	@echo "  install-tkinter     Install tkinter"
	@echo "  install-mediamtx    Install mediamtx (for ffmpeg streamer)"
	@echo "  install-gstreamer   Install GStreamer (for gst streamer)"
	@echo ""
	@echo "  run                 Run the application"
	@echo "  check               Check system dependencies (ffmpeg, ffplay)"
	@echo "  stream              Run RTSP streamer with ffmpeg (VIDEO=path required)"
	@echo "  stream-gst          Run RTSP streamer with GStreamer (VIDEO=path required)"
	@echo "  streamer-gui        Run RTSP streamer GUI"
	@echo ""
	@echo "  lint                Run linter (ruff)"
	@echo "  format              Format code (ruff)"
	@echo "  typecheck           Run type checker (mypy)"
	@echo "  test                Run tests"
	@echo ""
	@echo "  clean               Remove build artifacts and cache"
	@echo "  help                Show this help message"

# Install Python dependencies
install:
	uv sync

# Install development dependencies
dev:
	uv sync --extra dev

# Install all system dependencies
install-system-deps: install-ffmpeg install-tkinter install-mediamtx

# Install ffmpeg
install-ffmpeg:
ifeq ($(UNAME_S),Darwin)
	@echo "Installing ffmpeg via Homebrew..."
	brew install ffmpeg
else
	@echo "Warning: Automatic installation only supported on macOS."
	@echo "Please install ffmpeg manually:"
	@echo "  Ubuntu/Debian: sudo apt install ffmpeg"
	@echo "  Fedora: sudo dnf install ffmpeg"
	@echo "  Arch: sudo pacman -S ffmpeg"
	@echo "  Windows: choco install ffmpeg"
endif

# Install tkinter
install-tkinter:
ifeq ($(UNAME_S),Darwin)
	@echo "Installing python-tk via Homebrew..."
	@# Detect Python version
	$(eval PY_VERSION := $(shell python3 --version 2>&1 | sed 's/Python \([0-9]*\.[0-9]*\).*/\1/'))
	brew install python-tk@$(PY_VERSION)
else
	@echo "Warning: Automatic installation only supported on macOS."
	@echo "Please install tkinter manually:"
	@echo "  Ubuntu/Debian: sudo apt install python3-tk"
	@echo "  Fedora: sudo dnf install python3-tkinter"
	@echo "  Arch: sudo pacman -S tk"
	@echo "  Windows: Tkinter is included with Python installer"
endif

# Install mediamtx (RTSP server for streamer)
install-mediamtx:
ifeq ($(UNAME_S),Darwin)
	@echo "Installing mediamtx via Homebrew..."
	brew install mediamtx
else
	@echo "Warning: Automatic installation only supported on macOS."
	@echo "Please install mediamtx manually:"
	@echo "  Download from: https://github.com/bluenviron/mediamtx/releases"
endif

# Install GStreamer (for gst streamer - recommended)
install-gstreamer:
ifeq ($(UNAME_S),Darwin)
	@echo "Installing GStreamer system libraries via Homebrew..."
	brew install gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-rtsp-server gobject-introspection
	@echo "Installing PyGObject Python package..."
	uv sync --extra gstreamer
else
	@echo "Warning: Automatic installation only supported on macOS."
	@echo "Please install GStreamer manually:"
	@echo "  Ubuntu/Debian: sudo apt install python3-gst-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gir1.2-gst-rtsp-server-1.0"
	@echo "  Fedora: sudo dnf install python3-gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-rtsp-server"
	@echo "  Arch: sudo pacman -S gst-python gst-plugins-base gst-plugins-good gst-plugins-bad gst-rtsp-server"
	@echo "Then run: uv sync --extra gstreamer"
endif

# Run the application
run:
	uv run python -m rtsp_viewer

# Check system dependencies
check:
	uv run python -m rtsp_viewer --check

# Run the RTSP streamer with ffmpeg+mediamtx (requires VIDEO=path/to/video.mp4)
stream:
ifndef VIDEO
	@echo "Usage: make stream VIDEO=path/to/video.mp4 [PORT=8554] [NAME=stream]"
	@echo ""
	@echo "Example: make stream VIDEO=test.mp4"
	@echo "         make stream VIDEO=test.mp4 PORT=8555 NAME=cam1"
else
	uv run rtsp-streamer $(VIDEO) $(if $(PORT),-p $(PORT)) $(if $(NAME),-n $(NAME))
endif

# Run the RTSP streamer with GStreamer (recommended - requires VIDEO=path/to/video.mp4)
stream-gst:
ifndef VIDEO
	@echo "Usage: make stream-gst VIDEO=path/to/video.mp4 [PORT=8554] [NAME=stream] [LOOP=1]"
	@echo ""
	@echo "Example: make stream-gst VIDEO=test.mp4"
	@echo "         make stream-gst VIDEO=test.mp4 PORT=8555 NAME=cam1"
	@echo "         make stream-gst VIDEO=test.mp4 LOOP=1"
else
	uv run rtsp-streamer-gst $(VIDEO) $(if $(PORT),-p $(PORT)) $(if $(NAME),-n $(NAME)) $(if $(LOOP),--loop)
endif

# Run the RTSP streamer GUI
streamer-gui:
	uv run rtsp-streamer-gui

# Run linter
lint:
	uv run ruff check src/

# Format code
format:
	uv run ruff format src/
	uv run ruff check --fix src/

# Run type checker
typecheck:
	uv run mypy src/

# Run tests (placeholder for future tests)
test:
	@echo "No tests implemented yet"

# Clean build artifacts and cache
clean:
	rm -rf __pycache__ .mypy_cache .ruff_cache
	rm -rf *.egg-info build dist src/*.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
