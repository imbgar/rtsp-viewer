.PHONY: install dev lint format typecheck test clean run check help

# Default target
help:
	@echo "RTSP Viewer - Available targets:"
	@echo ""
	@echo "  install    Install production dependencies"
	@echo "  dev        Install development dependencies"
	@echo "  run        Run the application"
	@echo "  check      Check system dependencies (ffmpeg, ffplay)"
	@echo ""
	@echo "  lint       Run linter (ruff)"
	@echo "  format     Format code (ruff)"
	@echo "  typecheck  Run type checker (mypy)"
	@echo "  test       Run tests"
	@echo ""
	@echo "  clean      Remove build artifacts and cache"
	@echo "  help       Show this help message"

# Install production dependencies
install:
	uv sync

# Install development dependencies
dev:
	uv sync --extra dev

# Run the application
run:
	uv run python main.py

# Check system dependencies
check:
	uv run python main.py --check

# Run linter
lint:
	uv run ruff check .

# Format code
format:
	uv run ruff format .
	uv run ruff check --fix .

# Run type checker
typecheck:
	uv run mypy --ignore-missing-imports .

# Run tests (placeholder for future tests)
test:
	@echo "No tests implemented yet"

# Clean build artifacts and cache
clean:
	rm -rf __pycache__ .mypy_cache .ruff_cache
	rm -rf *.egg-info build dist
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
