.PHONY: install dev lint format typecheck test clean run check help install-ffmpeg install-tkinter install-system-deps

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
	@echo ""
	@echo "  run                 Run the application"
	@echo "  check               Check system dependencies (ffmpeg, ffplay)"
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
install-system-deps: install-ffmpeg install-tkinter

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

# Run the application
run:
	uv run python -m rtsp_viewer

# Check system dependencies
check:
	uv run python -m rtsp_viewer --check

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
