"""GUI for RTSP stream viewer using tkinter."""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image, ImageTk

from logger import add_gui_handler, remove_gui_handler, GUILogHandler

if TYPE_CHECKING:
    from viewer import RTSPViewer


class ViewerGUI:
    """Main GUI window for RTSP stream viewing and recording."""

    def __init__(self, viewer: "RTSPViewer"):
        self.viewer = viewer
        self.root = tk.Tk()
        self.root.title("RTSP Stream Viewer")
        self.root.geometry("1024x768")
        self.root.minsize(800, 600)

        # Image reference to prevent garbage collection
        self._photo: ImageTk.PhotoImage | None = None
        self._update_scheduled = False

        # Console log handling
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._log_handler: GUILogHandler | None = None
        self._console_visible = False

        self._setup_ui()
        self._setup_bindings()
        self._setup_log_handler()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        # Main container
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Top bar with camera info
        self._setup_info_bar()

        # Video display area
        self._setup_video_display()

        # Control buttons
        self._setup_controls()

        # Status bar
        self._setup_status_bar()

        # Console panel (initially hidden)
        self._setup_console_panel()

    def _setup_info_bar(self) -> None:
        """Set up the information bar at the top."""
        info_frame = ttk.Frame(self.main_frame)
        info_frame.pack(fill=tk.X, pady=(0, 5))

        # Camera selector (for future multi-camera support)
        ttk.Label(info_frame, text="Camera:").pack(side=tk.LEFT, padx=(0, 5))

        self.camera_var = tk.StringVar()
        self.camera_combo = ttk.Combobox(
            info_frame, textvariable=self.camera_var, state="readonly", width=30
        )
        self.camera_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.camera_combo.bind("<<ComboboxSelected>>", self._on_camera_selected)

        # Refresh config button
        self.refresh_btn = ttk.Button(
            info_frame, text="Refresh Config", command=self._on_refresh_config
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=5)

        # Stream info label
        self.info_label = ttk.Label(info_frame, text="")
        self.info_label.pack(side=tk.RIGHT, padx=5)

    def _setup_video_display(self) -> None:
        """Set up the video display area."""
        # Frame for video with border
        video_frame = ttk.LabelFrame(self.main_frame, text="Video Feed")
        video_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # Canvas for video display
        self.video_canvas = tk.Canvas(video_frame, bg="black")
        self.video_canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Placeholder text
        self.video_canvas.create_text(
            400,
            300,
            text="No stream connected\nClick 'Play' to start",
            fill="white",
            font=("Arial", 16),
            justify=tk.CENTER,
            tags="placeholder",
        )

    def _setup_controls(self) -> None:
        """Set up the control buttons."""
        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill=tk.X, pady=5)

        # Center the buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.pack()

        # Play button
        self.play_btn = ttk.Button(
            button_frame, text="Play", command=self._on_play, width=12
        )
        self.play_btn.pack(side=tk.LEFT, padx=5)

        # Pause button
        self.pause_btn = ttk.Button(
            button_frame, text="Pause", command=self._on_pause, width=12
        )
        self.pause_btn.pack(side=tk.LEFT, padx=5)
        self.pause_btn.state(["disabled"])

        # Record button
        self.record_btn = ttk.Button(
            button_frame, text="Record", command=self._on_record, width=12
        )
        self.record_btn.pack(side=tk.LEFT, padx=5)
        self.record_btn.state(["disabled"])

        # Stop Recording button
        self.stop_record_btn = ttk.Button(
            button_frame, text="Stop Recording", command=self._on_stop_record, width=12
        )
        self.stop_record_btn.pack(side=tk.LEFT, padx=5)
        self.stop_record_btn.state(["disabled"])

        # Separator
        ttk.Separator(button_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # Audio Preview toggle (live audio playback)
        self.audio_preview_var = tk.BooleanVar(value=True)
        self.audio_preview_check = ttk.Checkbutton(
            button_frame, text="Audio Preview", variable=self.audio_preview_var,
            command=self._on_audio_preview_toggle
        )
        self.audio_preview_check.pack(side=tk.LEFT, padx=5)

        # Record Audio toggle (include audio in recording)
        self.record_audio_var = tk.BooleanVar(value=True)
        self.record_audio_check = ttk.Checkbutton(
            button_frame, text="Record Audio", variable=self.record_audio_var
        )
        self.record_audio_check.pack(side=tk.LEFT, padx=5)

        # Separator
        ttk.Separator(button_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # Console toggle button
        self.console_btn = ttk.Button(
            button_frame, text="Console", command=self._toggle_console, width=10
        )
        self.console_btn.pack(side=tk.LEFT, padx=5)

    def _setup_status_bar(self) -> None:
        """Set up the status bar at the bottom."""
        status_frame = ttk.Frame(self.main_frame)
        status_frame.pack(fill=tk.X, pady=(5, 0))

        # Status label
        self.status_label = ttk.Label(status_frame, text="Ready")
        self.status_label.pack(side=tk.LEFT)

        # FPS label
        self.fps_label = ttk.Label(status_frame, text="")
        self.fps_label.pack(side=tk.RIGHT, padx=10)

        # Recording indicator
        self.recording_label = ttk.Label(status_frame, text="", foreground="red")
        self.recording_label.pack(side=tk.RIGHT, padx=10)

    def _setup_console_panel(self) -> None:
        """Set up the console log panel (initially hidden)."""
        self.console_frame = ttk.LabelFrame(self.main_frame, text="Console")

        # Text widget with scrollbar
        console_inner = ttk.Frame(self.console_frame)
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
            self.console_frame, text="Clear", command=self._clear_console, width=8
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

    def _toggle_console(self) -> None:
        """Toggle the console panel visibility."""
        if self._console_visible:
            self.console_frame.pack_forget()
            self._console_visible = False
        else:
            self.console_frame.pack(fill=tk.X, pady=(5, 0))
            self._console_visible = True

    def _clear_console(self) -> None:
        """Clear the console text."""
        self.console_text.configure(state=tk.NORMAL)
        self.console_text.delete("1.0", tk.END)
        self.console_text.configure(state=tk.DISABLED)

    def _setup_bindings(self) -> None:
        """Set up keyboard and event bindings."""
        self.root.bind("<space>", lambda e: self._toggle_playback())
        self.root.bind("<r>", lambda e: self._toggle_recording())
        self.root.bind("<Escape>", lambda e: self._on_close())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Handle window resize
        self.video_canvas.bind("<Configure>", self._on_canvas_resize)

    def _on_canvas_resize(self, event: tk.Event) -> None:
        """Handle canvas resize to reposition placeholder."""
        self.video_canvas.delete("placeholder")
        if not self.viewer.is_streaming():
            self.video_canvas.create_text(
                event.width // 2,
                event.height // 2,
                text="No stream connected\nClick 'Play' to start",
                fill="white",
                font=("Arial", 16),
                justify=tk.CENTER,
                tags="placeholder",
            )

    def _on_camera_selected(self, event: tk.Event) -> None:
        """Handle camera selection change."""
        selection = self.camera_combo.current()
        if selection >= 0:
            # Stop current stream if playing
            if self.viewer.is_streaming():
                self.viewer.stop_stream()
                self._update_button_states()

            self.viewer.select_camera(selection)
            self._update_status(f"Selected: {self.viewer.get_current_camera().name}")

    def _on_refresh_config(self) -> None:
        """Handle refresh configuration button click."""
        was_streaming = self.viewer.is_streaming()
        was_recording = self.viewer.is_recording()

        if was_streaming:
            self.viewer.stop_stream()

        try:
            self.viewer.reload_config()
            self._update_camera_list()
            self._update_status("Configuration reloaded successfully")
        except Exception as e:
            self._update_status(f"Config reload failed: {e}")

    def _on_play(self) -> None:
        """Handle play button click."""
        if self.viewer.get_current_camera() is None:
            messagebox.showwarning("Warning", "No camera selected.")
            return

        self._update_status("Connecting...")
        self.play_btn.state(["disabled"])

        # Start stream in background
        def start_stream():
            success = self.viewer.start_stream(
                enable_audio=self.audio_preview_var.get()
            )
            self.root.after(0, lambda: self._on_stream_started(success))

        threading.Thread(target=start_stream, daemon=True).start()

    def _on_stream_started(self, success: bool) -> None:
        """Handle stream start result."""
        if success:
            self._update_status("Streaming")
            self._update_button_states()
            self._start_video_update()
        else:
            self._update_status("Connection failed")
            self.play_btn.state(["!disabled"])
            messagebox.showerror(
                "Error", "Failed to connect to the camera.\nCheck the configuration and network."
            )

    def _on_pause(self) -> None:
        """Handle pause button click."""
        self.viewer.stop_stream()
        self._update_button_states()
        self._update_status("Paused")
        self._show_placeholder()

    def _on_record(self) -> None:
        """Handle record button click."""
        if not self.viewer.is_streaming():
            messagebox.showwarning("Warning", "Start streaming before recording.")
            return

        success = self.viewer.start_recording(record_audio=self.record_audio_var.get())
        if success:
            self._update_button_states()
            self._update_status("Recording")
            self._update_recording_indicator()
        else:
            messagebox.showerror("Error", "Failed to start recording.\nMake sure ffmpeg is installed.")

    def _on_stop_record(self) -> None:
        """Handle stop recording button click."""
        session_dir = self.viewer.stop_recording()
        self._update_button_states()
        self._update_status("Streaming")
        self.recording_label.config(text="")

        if session_dir:
            messagebox.showinfo("Recording Saved", f"Recording saved to:\n{session_dir}")

    def _on_audio_preview_toggle(self) -> None:
        """Handle audio preview checkbox toggle."""
        if self.viewer.is_streaming():
            if self.audio_preview_var.get():
                self.viewer.enable_audio()
            else:
                self.viewer.disable_audio()

    def _toggle_playback(self) -> None:
        """Toggle between play and pause."""
        if self.viewer.is_streaming():
            self._on_pause()
        else:
            self._on_play()

    def _toggle_recording(self) -> None:
        """Toggle recording state."""
        if self.viewer.is_recording():
            self._on_stop_record()
        elif self.viewer.is_streaming():
            self._on_record()

    def _update_button_states(self) -> None:
        """Update button states based on current viewer state."""
        streaming = self.viewer.is_streaming()
        recording = self.viewer.is_recording()

        if streaming:
            self.play_btn.state(["disabled"])
            self.pause_btn.state(["!disabled"])
            self.record_btn.state(["!disabled"] if not recording else ["disabled"])
            self.stop_record_btn.state(["!disabled"] if recording else ["disabled"])
        else:
            self.play_btn.state(["!disabled"])
            self.pause_btn.state(["disabled"])
            self.record_btn.state(["disabled"])
            self.stop_record_btn.state(["disabled"])

    def _update_status(self, message: str) -> None:
        """Update the status bar message."""
        self.status_label.config(text=message)

    def _update_recording_indicator(self) -> None:
        """Update the recording indicator."""
        if self.viewer.is_recording():
            duration = self.viewer.get_recording_duration()
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            self.recording_label.config(text=f"REC {minutes:02d}:{seconds:02d}")
            self.root.after(1000, self._update_recording_indicator)
        else:
            self.recording_label.config(text="")

    def _show_placeholder(self) -> None:
        """Show the placeholder text on the canvas."""
        self.video_canvas.delete("all")
        width = self.video_canvas.winfo_width()
        height = self.video_canvas.winfo_height()
        self.video_canvas.create_text(
            width // 2,
            height // 2,
            text="Stream paused\nClick 'Play' to resume",
            fill="white",
            font=("Arial", 16),
            justify=tk.CENTER,
            tags="placeholder",
        )

    def _start_video_update(self) -> None:
        """Start the video frame update loop."""
        self._update_video_frame()

    def _update_video_frame(self) -> None:
        """Update the video display with the latest frame."""
        if not self.viewer.is_streaming():
            return

        frame = self.viewer.get_frame()
        if frame is not None:
            self._display_frame(frame)

        # Update stream info
        info = self.viewer.get_stream_info()
        fps = self.viewer.get_actual_fps()
        self.info_label.config(
            text=f"{info.width}x{info.height} @ {info.fps:.1f}fps ({info.codec})"
        )
        latency_str = f" | {info.latency_ms:.0f}ms" if info.latency_ms > 0 else ""
        self.fps_label.config(text=f"FPS: {fps:.1f}{latency_str}")

        # Schedule next update (~30 fps for display)
        self.root.after(33, self._update_video_frame)

    def _display_frame(self, frame: np.ndarray) -> None:
        """Display a frame on the canvas with optimized processing."""
        # Get canvas dimensions
        canvas_width = self.video_canvas.winfo_width()
        canvas_height = self.video_canvas.winfo_height()

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

        # Resize frame using INTER_LINEAR for good balance of speed and quality
        # INTER_NEAREST: fastest, blocky
        # INTER_LINEAR: fast, smooth (good default)
        # INTER_AREA: best for downscaling
        # INTER_LANCZOS4: highest quality, slowest
        if display_width < frame_width:
            # Downscaling - use INTER_AREA for best quality
            resized = cv2.resize(
                frame, (display_width, display_height), interpolation=cv2.INTER_AREA
            )
        else:
            # Upscaling - use INTER_LINEAR for speed
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
        self.video_canvas.delete("all")
        x = (canvas_width - display_width) // 2
        y = (canvas_height - display_height) // 2
        self.video_canvas.create_image(x, y, anchor=tk.NW, image=self._photo)

    def _update_camera_list(self) -> None:
        """Update the camera dropdown list."""
        cameras = self.viewer.get_cameras()
        camera_names = [cam.name for cam in cameras]
        self.camera_combo["values"] = camera_names

        if camera_names:
            self.camera_combo.current(0)
            self.viewer.select_camera(0)
            self._update_status(f"Selected: {cameras[0].name}")

    def _on_close(self) -> None:
        """Handle window close event."""
        # Remove log handler
        if self._log_handler:
            remove_gui_handler(self._log_handler)
            self._log_handler = None

        self.viewer.stop_all()
        self.root.destroy()

    def run(self) -> None:
        """Start the GUI main loop."""
        self._update_camera_list()
        self.root.mainloop()
