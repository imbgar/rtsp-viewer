# RTSP Stream Viewer

A production-ready RTSP stream viewer and recorder built with Python, OpenCV, and FFmpeg. Includes an RTSP streamer for testing without real cameras.

## Features

### Stream Viewing
- **Real-time RTSP playback** via OpenCV with FFmpeg backend
- **Synchronized audio** using FFplay with async resampling
- **Low-latency mode** with buffer draining for security monitoring
- **Auto-reconnect** with health monitoring (5 attempts, 2s delay, 10s timeout)
- **Multi-camera support** with hot-swappable YAML configuration

### Recording
- **Lossless video capture** — direct stream copy, no re-encoding
- **Crash-resistant** — fragmented MP4 preserves data on interruption
- **30-minute segments** — automatic file rotation for reliability
- **AAC audio** — transcoded to 128 kbps for broad compatibility

### RTSP Streamer
- **Test without cameras** — serve any video file as an RTSP stream
- **Two backends** — GStreamer (recommended) or FFmpeg + mediamtx
- **GUI and CLI** — visual interface or command-line control
- **Looping support** — continuous playback for extended testing

### User Interface
- **Native Tkinter GUI** — cross-platform, no web dependencies
- **Console panel** — built-in log viewer for debugging
- **State persistence** — remembers window size, audio settings, last camera
- **Open Streamer** — launch streamer directly from main viewer

---

## Quick Start

```bash
# Install dependencies
make install-system-deps
make install

# Configure cameras
cp cameras.yaml.example cameras.yaml  # Edit with your camera details

# Run the viewer
make run
```

---

## Requirements

| Dependency | Purpose | Install |
|------------|---------|---------|
| Python 3.11+ | Runtime | — |
| FFmpeg | Audio playback, recording | `brew install ffmpeg` |
| Tkinter | GUI framework | `brew install python-tk@3.13` |
| GStreamer | Streamer (optional) | `make install-gstreamer` |
| mediamtx | Streamer fallback (optional) | `make install-mediamtx` |

---

## Installation

### macOS (Homebrew)

```bash
# All system dependencies
make install-system-deps

# Python packages
make install
```

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install ffmpeg python3-tk

# For streamer
sudo apt install python3-gst-1.0 gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gir1.2-gst-rtsp-server-1.0

make install
```

### Verify Installation

```bash
make check
```

---

## Configuration

Create `cameras.yaml` in the project root:

```yaml
cameras:
  - name: "Front Door"
    address: "192.168.1.100"
    port: 554
    username: "admin"
    password: "password123"
    path: "/Streaming/Channels/101"
    low_latency: false

  - name: "Backyard"
    address: "192.168.1.101"
    port: 554
    username: "admin"
    password: "password123"
    path: "/h264Preview_01_main"
    low_latency: true
```

### Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Display name for the camera |
| `address` | string | required | IP address or hostname |
| `port` | int | `554` | RTSP port |
| `username` | string | `""` | Authentication username |
| `password` | string | `""` | Authentication password |
| `path` | string | `""` | RTSP stream path |
| `low_latency` | bool | `false` | Enable buffer draining for real-time display |

### Common RTSP Paths

| Manufacturer | Path |
|--------------|------|
| Hikvision | `/Streaming/Channels/101` |
| Dahua / Amcrest | `/cam/realmonitor?channel=1&subtype=0` |
| Reolink | `/h264Preview_01_main` |
| Wyze | `/live` |
| Axis | `/axis-media/media.amp` |
| Generic | `/stream1`, `/h264`, `/live` |

---

## Usage

### Viewer Application

```bash
# Start the GUI
make run

# Or with custom config
rtsp-viewer -c /path/to/cameras.yaml

# Check dependencies only
rtsp-viewer --check
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `R` | Start / Stop recording |
| `Escape` | Exit |

### GUI Controls

| Button | Action |
|--------|--------|
| Play | Connect and stream from selected camera |
| Pause | Disconnect from stream |
| Record | Start recording to `recordings/` directory |
| Audio | Toggle audio playback |
| Refresh | Reload camera configuration |
| Console | Show/hide log panel |
| Streamer | Open RTSP streamer window |

---

## Recording

Recordings are organized in session directories:

```
recordings/
└── Front_Door_20231215_143052/
    ├── Front_Door_20231215_143052.mp4   # 0:00 - 0:30
    ├── Front_Door_20231215_173052.mp4   # 0:30 - 1:00
    └── Front_Door_20231215_203052.mp4   # 1:00 - 1:30
```

### Recording Specifications

| Property | Value |
|----------|-------|
| Container | MP4 (fragmented) |
| Video | Stream copy (original codec) |
| Audio | AAC 128 kbps |
| Segments | 30 minutes each |
| Flags | `frag_keyframe+empty_moov+default_base_moof` |

---

## Low-Latency Mode

Enable `low_latency: true` for real-time monitoring scenarios.

| Behavior | Standard | Low-Latency |
|----------|----------|-------------|
| Buffer | 8 MB | None (`nobuffer`) |
| Frame handling | Sequential read | Buffer drain (latest only) |
| Typical latency | 1–3 seconds | < 500 ms |
| Smoothness | Consistent | May skip frames |

**Best for:** Security monitoring, PTZ control, live events where delay matters more than smoothness.

---

## RTSP Streamer

Test the viewer without real cameras by serving a video file as an RTSP stream.

### GUI Mode

```bash
make streamer-gui
```

1. Browse and select a video file
2. Choose backend (GStreamer recommended)
3. Click Start
4. Connect viewer to `rtsp://localhost:8554/stream`

### CLI Mode

```bash
# GStreamer backend (recommended)
make stream-gst VIDEO=test.mp4

# With options
make stream-gst VIDEO=test.mp4 PORT=8555 NAME=cam1 LOOP=1

# FFmpeg + mediamtx fallback
make stream VIDEO=test.mp4
```

### Backend Comparison

| Feature | GStreamer | FFmpeg + mediamtx |
|---------|-----------|-------------------|
| Stability | Better | Good |
| Looping | Supported | Restarts file |
| Setup | More packages | Two binaries |
| Recommendation | **Primary** | Fallback |

### Installing Streamer Dependencies

```bash
# GStreamer (recommended)
make install-gstreamer

# Or FFmpeg + mediamtx
make install-mediamtx
```

---

## Architecture

### Unified Stream Design

```
┌─────────────────────────────────────────────────────────┐
│                     UnifiedStream                       │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   OpenCV     │  │   FFplay     │  │   FFmpeg     │  │
│  │  (display)   │  │   (audio)    │  │  (record)    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         └─────────────────┴─────────────────┘          │
│                           │                             │
│                    RTSP Stream (TCP)                    │
└─────────────────────────────────────────────────────────┘
```

### Thread Model

| Thread | Purpose | Lifecycle |
|--------|---------|-----------|
| Main | Tkinter event loop | Application lifetime |
| Capture | Frame reading (OpenCV) | While streaming |
| Recording | FFmpeg process monitoring | While recording |

### Key Modules

```
src/rtsp_viewer/
├── cli.py                    # Entry point, argument parsing
├── core/
│   ├── config.py             # YAML camera configuration
│   ├── unified_stream.py     # Video, audio, recording manager
│   ├── viewer.py             # Multi-camera controller
│   ├── streamer.py           # FFmpeg + mediamtx streamer
│   └── gst_streamer.py       # GStreamer streamer
├── ui/
│   ├── gui.py                # Main viewer window
│   └── streamer_gui.py       # Streamer control window
└── utils/
    ├── logger.py             # Logging with GUI handler
    └── state.py              # Persistent settings
```

---

## Development

### Setup

```bash
make dev  # Install with dev dependencies
```

### Commands

| Command | Description |
|---------|-------------|
| `make run` | Start the application |
| `make lint` | Run ruff linter |
| `make format` | Format code with ruff |
| `make typecheck` | Run mypy type checker |
| `make clean` | Remove build artifacts |

### CLI Entry Points

| Command | Description |
|---------|-------------|
| `rtsp-viewer` | Main viewer application |
| `rtsp-streamer` | FFmpeg streamer CLI |
| `rtsp-streamer-gst` | GStreamer streamer CLI |
| `rtsp-streamer-gui` | Streamer GUI |

---

## Troubleshooting

### Stream won't connect

```bash
# Test with ffplay first
ffplay -rtsp_transport tcp "rtsp://user:pass@192.168.1.100:554/stream1"
```

- Check camera IP is reachable
- Verify credentials and RTSP path
- Try different paths from the manufacturer table

### No audio

- Confirm FFplay is installed: `which ffplay`
- Some cameras don't have audio streams
- Ensure Audio toggle is enabled in GUI

### Recording issues

- 0-byte files: stream must be playing before recording starts
- Choppy playback: files use fragmented MP4, some players struggle

### High CPU usage

- Disable low-latency mode
- Reduce window size (less scaling)
- Close unused camera streams

---

## License

MIT License — see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make changes and test: `make format && make lint`
4. Submit a pull request
