# RTSP Stream Viewer

A cross-platform RTSP stream viewer and recorder built with Python, OpenCV, and FFmpeg.

## Features

- **Live Streaming**: View RTSP camera feeds in real-time
- **Recording**: Record streams to MP4 with original video quality
- **Audio Playback**: Listen to camera audio (requires FFmpeg)
- **Multi-Camera Support**: Configure multiple cameras via YAML
- **Low-Latency Mode**: Optional optimizations for real-time monitoring
- **Hot Reload**: Refresh camera configuration without restarting

## Requirements

- Python 3.11+
- FFmpeg (for audio playback and recording)
- Tkinter (for GUI)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/rtsp-viewer.git
cd rtsp-viewer
```

### 2. Install system dependencies

#### macOS (Homebrew)

```bash
make install-system-deps
```

Or manually:

```bash
brew install ffmpeg
brew install python-tk@3.13  # Match your Python version
```

#### Ubuntu/Debian

```bash
sudo apt update
sudo apt install ffmpeg python3-tk
```

#### Fedora

```bash
sudo dnf install ffmpeg python3-tkinter
```

#### Arch Linux

```bash
sudo pacman -S ffmpeg tk
```

#### Windows

```powershell
choco install ffmpeg
# Tkinter is included with the Python installer
```

### 3. Install Python dependencies

```bash
# Using uv (recommended)
make install

# Or with pip
pip install -e .
```

### 4. Verify installation

```bash
make check
```

## Configuration

Create or edit `cameras.yaml` in the project root:

```yaml
cameras:
  - name: "Front Door"
    address: "192.168.1.100"
    port: 554
    username: "admin"
    password: "password123"
    path: "/stream1"
    low_latency: false

  - name: "Backyard"
    address: "192.168.1.101"
    port: 554
    username: "admin"
    password: "password123"
    path: "/h264"
    low_latency: true
```

### Configuration Options

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Display name for the camera |
| `address` | string | Yes | - | IP address or hostname |
| `port` | integer | No | 554 | RTSP port |
| `username` | string | No | "" | Authentication username |
| `password` | string | No | "" | Authentication password |
| `path` | string | No | "" | RTSP stream path |
| `low_latency` | boolean | No | false | Enable low-latency optimizations |

### Common RTSP Paths by Manufacturer

| Manufacturer | Common Paths |
|--------------|--------------|
| Hikvision | `/Streaming/Channels/101` |
| Dahua | `/cam/realmonitor?channel=1&subtype=0` |
| Wyze | `/live` |
| Amcrest | `/cam/realmonitor?channel=1&subtype=0` |
| Reolink | `/h264Preview_01_main` |
| Axis | `/axis-media/media.amp` |
| Generic | `/stream1`, `/h264`, `/live`, `/video1` |

## Usage

### Start the application

```bash
make run
```

Or directly:

```bash
uv run python main.py
```

### Command-line options

```bash
uv run python main.py --help

# Use a custom config file
uv run python main.py -c /path/to/cameras.yaml

# Check dependencies only
uv run python main.py --check
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Toggle play/pause |
| `R` | Toggle recording |
| `Escape` | Exit application |

### GUI Controls

- **Play**: Start streaming from selected camera
- **Pause**: Stop streaming
- **Record**: Start recording to `recordings/` folder
- **Stop Recording**: Stop and finalize recording
- **Audio**: Toggle audio playback on/off
- **Refresh Config**: Reload `cameras.yaml` without restarting

## Recording

Recordings are saved to the `recordings/` directory with timestamped filenames:

```
recordings/
├── Front_Door_20231215_143052.mp4
├── Front_Door_20231215_151230.mp4
└── Backyard_20231215_160045.mp4
```

### Recording Format

- **Container**: MP4
- **Video**: Original codec (no re-encoding)
- **Audio**: AAC 128kbps (transcoded for compatibility)
- **Optimization**: `faststart` flag for web streaming

## Low-Latency Mode

Enable `low_latency: true` in camera config for:

- Reduced buffering
- Frame dropping for real-time display
- Faster stream startup

**Trade-offs**: May result in occasional frame skips. Best for security monitoring where real-time matters more than smoothness.

## Development

### Setup development environment

```bash
make dev
```

### Available make targets

```bash
make help
```

| Target | Description |
|--------|-------------|
| `install` | Install Python dependencies |
| `dev` | Install development dependencies |
| `install-system-deps` | Install FFmpeg and Tkinter (macOS) |
| `run` | Run the application |
| `check` | Verify system dependencies |
| `lint` | Run ruff linter |
| `format` | Format code with ruff |
| `typecheck` | Run mypy type checker |
| `clean` | Remove build artifacts |

### Project Structure

```
rtsp-viewer/
├── main.py          # Application entry point
├── gui.py           # Tkinter GUI implementation
├── viewer.py        # Main controller
├── stream.py        # RTSP stream handler (OpenCV)
├── audio.py         # Audio playback (FFplay)
├── recorder.py      # Recording functionality (FFmpeg)
├── config.py        # YAML configuration loader
├── cameras.yaml     # Camera configuration
├── Makefile         # Build automation
├── pyproject.toml   # Python project configuration
└── README.md        # This file
```

## Troubleshooting

### Stream won't connect

1. Verify the RTSP URL works with VLC or ffplay:
   ```bash
   ffplay -rtsp_transport tcp "rtsp://user:pass@192.168.1.100:554/stream1"
   ```

2. Check firewall settings on camera and network

3. Try different RTSP paths (see manufacturer table above)

### No audio

- Ensure FFmpeg/FFplay is installed: `which ffplay`
- Some cameras don't have audio or require separate audio paths
- Check the Audio checkbox is enabled

### Recording creates 0-byte files

- Camera audio codec may be incompatible (fixed in latest version)
- Check FFmpeg is installed: `which ffmpeg`
- Verify stream is actually playing before recording

### High CPU usage

- Disable `low_latency` mode
- Reduce window size (less scaling needed)
- Close other camera streams

### Ghosting/motion blur

- This is often from the camera's encoding, not the viewer
- Try enabling `low_latency: true` for buffer draining
- Some cameras have "low latency" or "smooth" encoding options

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes
4. Run linting: `make format && make lint`
5. Submit a pull request
