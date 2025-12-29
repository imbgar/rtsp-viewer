"""GUI for RTSP streamer using tkinter."""

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from rtsp_viewer.core.gst_streamer import GstRTSPStreamer
from rtsp_viewer.core.streamer import DEFAULT_PORT, RTSPStreamer
from rtsp_viewer.utils.logger import GUILogHandler, add_gui_handler, get_logger, remove_gui_handler
from rtsp_viewer.utils.state import AppState

log = get_logger("streamer_gui")

class StreamerGUI:
    """GUI window for RTSP streamer."""

    def __init__(self, parent: tk.Tk | None = None):
        """Initialize the streamer GUI.

        Args:
            parent: Parent window. If None, creates a new root window.
        """
        self._is_toplevel = parent is not None

        if parent:
            self.root = tk.Toplevel(parent)
        else:
            self.root = tk.Tk()

        self.root.title("PyRTSP Streamer")
        self.root.geometry("800x700")
        self.root.minsize(600, 500)

        # Set application icon (only for standalone mode)
        if not self._is_toplevel:
            self._set_app_icon()

        # Streamer instance (can be RTSPStreamer or GstRTSPStreamer)
        self._streamer: RTSPStreamer | GstRTSPStreamer | None = None
        self._video_path: Path | None = None

        # Preview state
        self._preview_running = False
        self._preview_cap: cv2.VideoCapture | None = None
        self._photo: ImageTk.PhotoImage | None = None

        # Console log handling
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._log_handler: GUILogHandler | None = None

        # State persistence
        self._state = AppState()

        self._setup_ui()
        self._setup_bindings()
        self._setup_log_handler()
        self._check_dependencies()
        self._restore_state()

    def _set_app_icon(self) -> None:
        """Set the application icon for dock/taskbar."""
        icons_dir = Path(__file__).parent.parent.parent.parent / "assets" / "icons"
        png_path = icons_dir / "icon.png"
        icns_path = icons_dir / "rtsp_viewer.icns"

        # Set window icon using PNG (works cross-platform)
        if png_path.exists():
            try:
                icon_image = Image.open(png_path)
                icon_photo = ImageTk.PhotoImage(icon_image)
                self.root.iconphoto(True, icon_photo)
                self._icon_photo = icon_photo  # Keep reference to prevent GC
            except Exception:
                pass

        # macOS: Set dock icon using PyObjC if available
        if sys.platform == "darwin" and icns_path.exists():
            try:
                from AppKit import NSApplication, NSImage
                app = NSApplication.sharedApplication()
                icon = NSImage.alloc().initWithContentsOfFile_(str(icns_path))
                if icon:
                    app.setApplicationIconImage_(icon)
            except ImportError:
                pass

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        # Main container
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Configuration section
        self._setup_config_section()

        # Preview section
        self._setup_preview_section()

        # Control buttons
        self._setup_controls()

        # Status bar
        self._setup_status_bar()

        # Console panel
        self._setup_console_panel()

    def _setup_config_section(self) -> None:
        """Set up the configuration options section."""
        config_frame = ttk.LabelFrame(self.main_frame, text="Configuration")
        config_frame.pack(fill=tk.X, pady=(0, 10))

        # Video file selection
        file_frame = ttk.Frame(config_frame)
        file_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(file_frame, text="Video File:").pack(side=tk.LEFT)

        self.file_var = tk.StringVar()
        self.file_entry = ttk.Entry(file_frame, textvariable=self.file_var, state="readonly")
        self.file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 5))

        self.browse_btn = ttk.Button(
            file_frame, text="Browse...", command=self._on_browse
        )
        self.browse_btn.pack(side=tk.LEFT)

        # Port and stream name
        options_frame = ttk.Frame(config_frame)
        options_frame.pack(fill=tk.X, padx=10, pady=5)

        # Port
        ttk.Label(options_frame, text="Port:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.port_entry = ttk.Entry(options_frame, textvariable=self.port_var, width=8)
        self.port_entry.pack(side=tk.LEFT, padx=(5, 20))

        # Stream name
        ttk.Label(options_frame, text="Stream Name:").pack(side=tk.LEFT)
        self.stream_name_var = tk.StringVar(value="stream")
        self.stream_name_entry = ttk.Entry(
            options_frame, textvariable=self.stream_name_var, width=20
        )
        self.stream_name_entry.pack(side=tk.LEFT, padx=(5, 20))

        # Backend selection
        backend_frame = ttk.Frame(config_frame)
        backend_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(backend_frame, text="Backend:").pack(side=tk.LEFT)
        default_backend = "gstreamer" if GstRTSPStreamer.is_available() else "ffmpeg"
        self.backend_var = tk.StringVar(value=default_backend)
        self.backend_combo = ttk.Combobox(
            backend_frame,
            textvariable=self.backend_var,
            values=["gstreamer", "ffmpeg"],
            state="readonly",
            width=12,
        )
        self.backend_combo.pack(side=tk.LEFT, padx=(5, 10))

        # Backend status label
        self.backend_status = ttk.Label(backend_frame, text="", foreground="gray")
        self.backend_status.pack(side=tk.LEFT, padx=5)
        self._update_backend_status()

        # Update status when backend selection changes
        self.backend_combo.bind("<<ComboboxSelected>>", lambda e: self._update_backend_status())

        # RTSP URL display
        url_frame = ttk.Frame(config_frame)
        url_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(url_frame, text="RTSP URL:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar(value=f"rtsp://localhost:{DEFAULT_PORT}/stream")
        self.url_label = ttk.Label(
            url_frame, textvariable=self.url_var, foreground="blue"
        )
        self.url_label.pack(side=tk.LEFT, padx=(10, 5))

        self.copy_btn = ttk.Button(
            url_frame, text="Copy", command=self._copy_url, width=6
        )
        self.copy_btn.pack(side=tk.LEFT)

        # Update URL when port or stream name changes
        self.port_var.trace_add("write", self._update_url)
        self.stream_name_var.trace_add("write", self._update_url)

    def _setup_preview_section(self) -> None:
        """Set up the video preview section."""
        preview_frame = ttk.LabelFrame(self.main_frame, text="Preview")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Canvas for video preview
        self.preview_canvas = tk.Canvas(preview_frame, bg="black", height=300)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Placeholder text
        self.preview_canvas.create_text(
            300,
            150,
            text="No video loaded\nSelect a video file to preview",
            fill="white",
            font=("Arial", 12),
            justify=tk.CENTER,
            tags="placeholder",
        )

    def _setup_controls(self) -> None:
        """Set up the control buttons."""
        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill=tk.X, pady=(0, 10))

        # Center the buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.pack()

        # Start button
        self.start_btn = ttk.Button(
            button_frame, text="Start Streamer", command=self._on_start, width=15
        )
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.start_btn.state(["disabled"])

        # Stop button
        self.stop_btn = ttk.Button(
            button_frame, text="Stop Streamer", command=self._on_stop, width=15
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn.state(["disabled"])

        # Preview toggle
        self.preview_var = tk.BooleanVar(value=True)
        self.preview_check = ttk.Checkbutton(
            button_frame, text="Show Preview", variable=self.preview_var,
            command=self._on_preview_toggle
        )
        self.preview_check.pack(side=tk.LEFT, padx=20)

        # Stream audio toggle
        self.stream_audio_var = tk.BooleanVar(value=True)
        self.stream_audio_check = ttk.Checkbutton(
            button_frame, text="Stream Audio", variable=self.stream_audio_var
        )
        self.stream_audio_check.pack(side=tk.LEFT, padx=5)

    def _setup_status_bar(self) -> None:
        """Set up the status bar."""
        status_frame = ttk.Frame(self.main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))

        # Status label
        self.status_label = ttk.Label(status_frame, text="Ready")
        self.status_label.pack(side=tk.LEFT)

        # Streamer status indicator
        self.streamer_status_label = ttk.Label(status_frame, text="", foreground="gray")
        self.streamer_status_label.pack(side=tk.RIGHT, padx=10)

    def _setup_console_panel(self) -> None:
        """Set up the console log panel."""
        console_frame = ttk.LabelFrame(self.main_frame, text="Console")
        console_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 0))

        # Text widget with scrollbar
        console_inner = ttk.Frame(console_frame)
        console_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.console_text = tk.Text(
            console_inner,
            height=8,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            state=tk.DISABLED,
        )

        console_scrollbar = ttk.Scrollbar(
            console_inner, orient=tk.VERTICAL, command=self.console_text.yview
        )
        self.console_text.configure(yscrollcommand=console_scrollbar.set)

        console_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.console_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Clear button
        clear_btn = ttk.Button(
            console_frame, text="Clear", command=self._clear_console, width=8
        )
        clear_btn.pack(side=tk.RIGHT, padx=5, pady=2)

    def _setup_log_handler(self) -> None:
        """Set up the log handler for GUI console."""
        def log_callback(msg: str) -> None:
            self._log_queue.put(msg)

        self._log_handler = add_gui_handler(log_callback)
        self._process_log_queue()

    def _process_log_queue(self) -> None:
        """Process queued log messages and add them to the console."""
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._append_to_console(msg)
        except queue.Empty:
            pass

        # Schedule next check
        self.root.after(100, self._process_log_queue)

    def _append_to_console(self, msg: str) -> None:
        """Append a message to the console text widget."""
        self.console_text.configure(state=tk.NORMAL)
        self.console_text.insert(tk.END, msg + "\n")

        # Limit to 1000 lines
        line_count = int(self.console_text.index("end-1c").split(".")[0])
        if line_count > 1000:
            self.console_text.delete("1.0", f"{line_count - 1000}.0")

        self.console_text.see(tk.END)
        self.console_text.configure(state=tk.DISABLED)

    def _clear_console(self) -> None:
        """Clear the console text."""
        self.console_text.configure(state=tk.NORMAL)
        self.console_text.delete("1.0", tk.END)
        self.console_text.configure(state=tk.DISABLED)

    def _setup_bindings(self) -> None:
        """Set up keyboard and event bindings."""
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.preview_canvas.bind("<Configure>", self._on_canvas_resize)

    def _check_dependencies(self) -> None:
        """Check if required dependencies are available."""
        # Check ffmpeg backend
        ffmpeg_deps = RTSPStreamer.check_dependencies()
        ffmpeg_ok = all(ffmpeg_deps.values())

        # Check GStreamer backend
        gst_deps = GstRTSPStreamer.check_dependencies()
        gst_ok = all(gst_deps.values())

        if gst_ok:
            log.info("GStreamer backend available (recommended)")
        else:
            log.warning(f"GStreamer not available: {GstRTSPStreamer.get_import_error()}")
            log.info(
                "Install with: brew install gstreamer gst-plugins-base "
                "gst-plugins-good gst-plugins-bad gst-rtsp-server pygobject3"
            )

        if ffmpeg_ok:
            log.info("FFmpeg backend available")
        else:
            missing = [k for k, v in ffmpeg_deps.items() if not v]
            log.warning(f"FFmpeg backend missing: {', '.join(missing)}")

        if not gst_ok and not ffmpeg_ok:
            self._update_status(
                "No streamer backends available - install GStreamer or ffmpeg+mediamtx"
            )

    def _update_backend_status(self) -> None:
        """Update the backend availability status display."""
        backend = self.backend_var.get()

        if backend == "gstreamer":
            if GstRTSPStreamer.is_available():
                self.backend_status.config(text="(available - recommended)", foreground="green")
            else:
                self.backend_status.config(text="(not installed)", foreground="red")
        else:  # ffmpeg
            if RTSPStreamer.is_available():
                self.backend_status.config(text="(available)", foreground="green")
            else:
                deps = RTSPStreamer.check_dependencies()
                missing = [k for k, v in deps.items() if not v]
                msg = f"(missing: {', '.join(missing)})"
                self.backend_status.config(text=msg, foreground="red")

    def _on_browse(self) -> None:
        """Handle browse button click."""
        filetypes = [
            ("Video files", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v"),
            ("All files", "*.*"),
        ]

        filepath = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=filetypes,
        )

        if filepath:
            self._video_path = Path(filepath)
            self.file_var.set(str(self._video_path))
            self.start_btn.state(["!disabled"])
            self._update_status(f"Loaded: {self._video_path.name}")
            log.info(f"Selected video: {self._video_path}")

            # Start preview
            if self.preview_var.get():
                self._start_preview()

    def _update_url(self, *args) -> None:
        """Update the displayed RTSP URL."""
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = DEFAULT_PORT

        stream_name = self.stream_name_var.get() or "stream"
        self.url_var.set(f"rtsp://localhost:{port}/{stream_name}")

    def _copy_url(self) -> None:
        """Copy the RTSP URL to clipboard."""
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url_var.get())
        self._update_status("URL copied to clipboard")

    def _on_start(self) -> None:
        """Handle start button click."""
        if not self._video_path:
            self._update_status("No video file selected")
            return

        backend = self.backend_var.get()

        # Check if selected backend is available
        if backend == "gstreamer":
            if not GstRTSPStreamer.is_available():
                self._update_status("GStreamer not available - run: make install-gstreamer")
                return
        else:  # ffmpeg
            if not RTSPStreamer.is_available():
                deps = RTSPStreamer.check_dependencies()
                missing = [k for k, v in deps.items() if not v]
                self._update_status(f"FFmpeg backend missing: {', '.join(missing)}")
                return

        # Get configuration
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = DEFAULT_PORT
            self.port_var.set(str(port))

        stream_name = self.stream_name_var.get() or "stream"

        # Create streamer based on selected backend
        if backend == "gstreamer":
            self._streamer = GstRTSPStreamer(
                video_path=self._video_path,
                port=port,
                stream_name=stream_name,
                enable_audio=self.stream_audio_var.get(),
            )
            log.info("Using GStreamer backend")
        else:
            self._streamer = RTSPStreamer(
                video_path=self._video_path,
                port=port,
                stream_name=stream_name,
                enable_audio=self.stream_audio_var.get(),
            )
            log.info("Using FFmpeg backend")

        self._update_status("Starting streamer...")
        self.start_btn.state(["disabled"])

        # Start in background thread
        def start():
            success = self._streamer.start()
            self.root.after(0, lambda: self._on_started(success))

        threading.Thread(target=start, daemon=True).start()

    def _on_started(self, success: bool) -> None:
        """Handle streamer start result."""
        if success:
            backend = self.backend_var.get()
            self._update_status(f"Streamer running ({backend})")
            self.streamer_status_label.config(text="STREAMING", foreground="green")
            self.stop_btn.state(["!disabled"])
            self.browse_btn.state(["disabled"])
            self.port_entry.state(["disabled"])
            self.stream_name_entry.state(["disabled"])
            self.stream_audio_check.state(["disabled"])
            self.backend_combo.state(["disabled"])

            # Monitor streamer status
            self._monitor_streamer()
        else:
            self._update_status("Failed to start streamer")
            self.start_btn.state(["!disabled"])

    def _on_stop(self) -> None:
        """Handle stop button click."""
        if self._streamer:
            self._update_status("Stopping streamer...")
            self._streamer.stop()
            self._streamer = None

        self._update_status("Streamer stopped")
        self.streamer_status_label.config(text="", foreground="gray")
        self.start_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])
        self.browse_btn.state(["!disabled"])
        self.port_entry.state(["!disabled"])
        self.stream_name_entry.state(["!disabled"])
        self.stream_audio_check.state(["!disabled"])
        self.backend_combo.state(["!disabled"])

    def _monitor_streamer(self) -> None:
        """Monitor streamer status and update UI."""
        if self._streamer and self._streamer.is_running():
            self.root.after(1000, self._monitor_streamer)
        elif self._streamer:
            # Streamer stopped unexpectedly
            log.warning("Streamer stopped unexpectedly")
            self._on_stop()

    def _on_preview_toggle(self) -> None:
        """Handle preview checkbox toggle."""
        if self.preview_var.get():
            if self._video_path:
                self._start_preview()
        else:
            self._stop_preview()

    def _start_preview(self) -> None:
        """Start video preview."""
        if self._preview_running or not self._video_path:
            return

        self._preview_cap = cv2.VideoCapture(str(self._video_path))
        if not self._preview_cap.isOpened():
            log.error(f"Could not open video: {self._video_path}")
            return

        self._preview_running = True
        self._update_preview_frame()
        log.info("Preview started")

    def _stop_preview(self) -> None:
        """Stop video preview."""
        self._preview_running = False
        if self._preview_cap:
            self._preview_cap.release()
            self._preview_cap = None
        self._show_placeholder()
        log.info("Preview stopped")

    def _update_preview_frame(self) -> None:
        """Update the preview display with the next frame."""
        if not self._preview_running or not self._preview_cap:
            return

        ret, frame = self._preview_cap.read()
        if not ret:
            # Loop back to start
            self._preview_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._preview_cap.read()
            if not ret:
                self._stop_preview()
                return

        self._display_frame(frame)

        # Schedule next update (~15 fps for preview)
        self.root.after(66, self._update_preview_frame)

    def _display_frame(self, frame: np.ndarray) -> None:
        """Display a frame on the preview canvas."""
        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            return

        # Calculate aspect ratio
        frame_height, frame_width = frame.shape[:2]
        frame_aspect = frame_width / frame_height
        canvas_aspect = canvas_width / canvas_height

        # Calculate display size maintaining aspect ratio
        if frame_aspect > canvas_aspect:
            display_width = canvas_width
            display_height = int(canvas_width / frame_aspect)
        else:
            display_height = canvas_height
            display_width = int(canvas_height * frame_aspect)

        # Resize frame
        if display_width < frame_width:
            resized = cv2.resize(
                frame, (display_width, display_height), interpolation=cv2.INTER_AREA
            )
        else:
            resized = cv2.resize(
                frame, (display_width, display_height), interpolation=cv2.INTER_LINEAR
            )

        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        # Convert to PIL Image
        image = Image.fromarray(rgb_frame)

        # Convert to PhotoImage
        self._photo = ImageTk.PhotoImage(image=image)

        # Display on canvas
        self.preview_canvas.delete("all")
        x = (canvas_width - display_width) // 2
        y = (canvas_height - display_height) // 2
        self.preview_canvas.create_image(x, y, anchor=tk.NW, image=self._photo)

    def _show_placeholder(self) -> None:
        """Show the placeholder text on the canvas."""
        self.preview_canvas.delete("all")
        width = self.preview_canvas.winfo_width()
        height = self.preview_canvas.winfo_height()
        self.preview_canvas.create_text(
            width // 2,
            height // 2,
            text="No video loaded\nSelect a video file to preview",
            fill="white",
            font=("Arial", 12),
            justify=tk.CENTER,
            tags="placeholder",
        )

    def _on_canvas_resize(self, event: tk.Event) -> None:
        """Handle canvas resize."""
        if not self._preview_running:
            self._show_placeholder()

    def _update_status(self, message: str) -> None:
        """Update the status bar message."""
        self.status_label.config(text=message)

    def _restore_state(self) -> None:
        """Restore UI state from saved preferences."""
        # Restore show preview setting
        self.preview_var.set(self._state.streamer_show_preview)

        # Restore stream audio setting
        self.stream_audio_var.set(self._state.streamer_audio_enabled)

        # Restore last video file if it still exists
        last_video = self._state.streamer_last_video
        if last_video:
            video_path = Path(last_video)
            if video_path.exists():
                self._video_path = video_path
                self.file_var.set(str(self._video_path))
                self.start_btn.state(["!disabled"])
                self._update_status(f"Loaded: {self._video_path.name}")
                log.info(f"Restored last video: {self._video_path}")

                # Start preview if enabled
                if self.preview_var.get():
                    self._start_preview()

    def _save_state(self) -> None:
        """Save current UI state."""
        self._state.streamer_show_preview = self.preview_var.get()
        self._state.streamer_audio_enabled = self.stream_audio_var.get()
        if self._video_path:
            self._state.streamer_last_video = str(self._video_path)
        self._state.save()

    def _on_close(self) -> None:
        """Handle window close event."""
        # Save state before closing
        self._save_state()

        # Stop streamer if running
        if self._streamer:
            self._streamer.stop()
            self._streamer = None

        # Stop preview
        self._stop_preview()

        # Remove log handler
        if self._log_handler:
            remove_gui_handler(self._log_handler)
            self._log_handler = None

        self.root.destroy()

    def run(self) -> None:
        """Start the GUI main loop (only for standalone mode)."""
        if not self._is_toplevel:
            self.root.mainloop()


def run_streamer_gui():
    """Entry point for running the streamer GUI standalone."""
    gui = StreamerGUI()
    gui.run()


if __name__ == "__main__":
    run_streamer_gui()
