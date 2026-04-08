"""Spot-Train Visual Viewer — 5-camera live video with depth overlay.

Tkinter-based X11 window running in a background thread.
Layout: 3-over-2 camera grid (75%) + split bottom bar (25%).
"""

from __future__ import annotations

import collections
import io
import logging
import threading
import time
import tkinter as tk
from datetime import datetime
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageTk

_log = logging.getLogger("spot_train.viewer")

# Camera sources in grid order: row1 (FL, FR, Back), row2 (Left, Right)
CAMERA_SOURCES = [
    "frontleft_fisheye_image",
    "frontright_fisheye_image",
    "back_fisheye_image",
    "left_fisheye_image",
    "right_fisheye_image",
]

DEPTH_SOURCES = [
    "frontleft_depth_in_visual_frame",
    "frontright_depth_in_visual_frame",
    "back_depth_in_visual_frame",
    "left_depth_in_visual_frame",
    "right_depth_in_visual_frame",
]

CAMERA_LABELS = ["Front Left", "Front Right", "Back", "Left", "Right"]

# Display rotation per camera (degrees CCW)
CAMERA_ROTATIONS = {
    "frontleft_fisheye_image": -78,
    "frontright_fisheye_image": -102,
    "left_fisheye_image": 0,
    "right_fisheye_image": 180,
    "back_fisheye_image": 0,
}

DEPTH_ROTATIONS = {
    "frontleft_depth_in_visual_frame": -78,
    "frontright_depth_in_visual_frame": -102,
    "left_depth_in_visual_frame": 0,
    "right_depth_in_visual_frame": 180,
    "back_depth_in_visual_frame": 0,
}


def _depth_colormap(raw_bytes: bytes, rows: int, cols: int) -> Image.Image:
    """Convert DEPTH_U16 to a colorized RGBA overlay."""
    arr = np.frombuffer(raw_bytes, dtype=np.uint16).reshape((rows, cols))
    valid = arr > 0
    if not valid.any():
        return Image.fromarray(np.zeros((rows, cols, 4), dtype=np.uint8), "RGBA")
    max_d = min(int(arr[valid].max()), 10000)
    norm = np.clip(arr.astype(np.float32) / max(max_d, 1), 0, 1)
    r = (norm * 255).astype(np.uint8)
    b = 255 - r
    a = np.where(valid, 100, 0).astype(np.uint8)
    return Image.fromarray(np.stack([r, np.zeros_like(r), b, a], axis=-1), "RGBA")


class SpotTrainViewer:
    """Tkinter 5-camera viewer with depth overlay and split bottom bar."""

    def __init__(
        self,
        frame_callback: Callable[[], dict[str, tuple[bytes, int, int, int]]] | None = None,
        *,
        title: str = "Spot-Train Viewer",
    ) -> None:
        self._frame_cb = frame_callback
        self._title = title
        self._running = False
        self._root: tk.Tk | None = None
        self._photo_refs: dict[str, Any] = {}
        self._show_depth = True
        self._live_images: dict[str, Image.Image] = {}
        self._live_depth: dict[str, Image.Image] = {}
        self._last_window_size = (0, 0)

        # Bottom pane buffers
        self._desc_buffer: collections.deque[tuple[str, str]] = collections.deque(maxlen=200)
        self._trace_buffer: collections.deque[tuple[str, str]] = collections.deque(maxlen=200)
        self._lock = threading.Lock()

    # -- Public API -------------------------------------------------------

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._run_ui, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass

    def push_description(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._desc_buffer.append((ts, text))
        self._schedule_bottom_refresh()

    def push_trace(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._trace_buffer.append((ts, text))
        self._schedule_bottom_refresh()

    # -- UI setup ---------------------------------------------------------

    def _run_ui(self) -> None:
        self._root = tk.Tk()
        self._root.title(self._title)
        self._root.geometry("1200x850")
        self._root.configure(bg="#1e1e1e")

        main = tk.Frame(self._root, bg="#1e1e1e")
        main.pack(fill=tk.BOTH, expand=True)
        main.rowconfigure(0, weight=75)
        main.rowconfigure(1, weight=25)
        main.columnconfigure(0, weight=1)

        # Camera grid: row 0 = 3 panels, row 1 = 2 panels
        self._img_frame = tk.Frame(main, bg="#1e1e1e")
        self._img_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._img_frame.rowconfigure(0, weight=1)
        self._img_frame.rowconfigure(1, weight=1)
        for c in range(3):
            self._img_frame.columnconfigure(c, weight=1)

        self._panels: list[tk.Label] = []
        self._panel_labels: list[tk.Label] = []

        # Row 1: FL, FR, Back (3 panels)
        for i in range(3):
            frame = tk.Frame(self._img_frame, bg="#2d2d2d", bd=1, relief=tk.SUNKEN)
            frame.grid(row=0, column=i, sticky="nsew", padx=2, pady=2)
            frame.rowconfigure(1, weight=1)
            frame.columnconfigure(0, weight=1)
            lbl = tk.Label(
                frame, text=CAMERA_LABELS[i], fg="#aaa", bg="#2d2d2d", font=("monospace", 9)
            )
            lbl.grid(row=0, column=0, sticky="w", padx=4)
            img_lbl = tk.Label(frame, bg="#1a1a1a", text="No signal", fg="#555")
            img_lbl.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
            self._panels.append(img_lbl)
            self._panel_labels.append(lbl)

        # Row 2: Left, Right (2 panels)
        for i in range(2):
            frame = tk.Frame(self._img_frame, bg="#2d2d2d", bd=1, relief=tk.SUNKEN)
            frame.grid(row=1, column=i, sticky="nsew", padx=2, pady=2)
            frame.rowconfigure(1, weight=1)
            frame.columnconfigure(0, weight=1)
            lbl = tk.Label(
                frame, text=CAMERA_LABELS[3 + i], fg="#aaa", bg="#2d2d2d", font=("monospace", 9)
            )
            lbl.grid(row=0, column=0, sticky="w", padx=4)
            img_lbl = tk.Label(frame, bg="#1a1a1a", text="No signal", fg="#555")
            img_lbl.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
            self._panels.append(img_lbl)
            self._panel_labels.append(lbl)

        # Bottom bar: split panes
        bottom = tk.Frame(main, bg="#1e1e1e")
        bottom.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))

        # Nav controls
        nav = tk.Frame(bottom, bg="#1e1e1e")
        nav.pack(fill=tk.X)

        self._btn_depth = tk.Button(
            nav,
            text="Depth: ON",
            command=self._toggle_depth,
            bg="#2a2a5a",
            fg="#88f",
            relief=tk.FLAT,
            padx=8,
        )
        self._btn_depth.pack(side=tk.LEFT, padx=2)

        self._status_label = tk.Label(
            nav, text="Waiting for video...", fg="#aaa", bg="#1e1e1e", font=("monospace", 10)
        )
        self._status_label.pack(side=tk.LEFT, padx=12)

        # Split text panes
        pane_frame = tk.PanedWindow(bottom, orient=tk.HORIZONTAL, bg="#1e1e1e", sashwidth=4)
        pane_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        self._desc_text = tk.Text(
            pane_frame,
            bg="#1a1a1a",
            fg="#ddd",
            font=("monospace", 10),
            wrap=tk.WORD,
            relief=tk.SUNKEN,
            bd=1,
        )
        self._desc_text.config(state=tk.DISABLED)
        pane_frame.add(self._desc_text, stretch="always")

        self._trace_text = tk.Text(
            pane_frame,
            bg="#1a1a1a",
            fg="#0f0",
            font=("monospace", 9),
            wrap=tk.WORD,
            relief=tk.SUNKEN,
            bd=1,
        )
        self._trace_text.config(state=tk.DISABLED)
        pane_frame.add(self._trace_text, stretch="always")

        self._root.bind("<Configure>", self._on_configure)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start video thread
        if self._frame_cb:
            threading.Thread(target=self._video_loop, daemon=True).start()

        self._root.mainloop()

    def _on_close(self) -> None:
        self._running = False
        self._root.destroy()

    def _on_configure(self, event: Any) -> None:
        if event.widget is not self._root:
            return
        new_size = (event.width, event.height)
        if new_size != self._last_window_size:
            self._last_window_size = new_size
            self._refresh_cameras()

    def _toggle_depth(self) -> None:
        self._show_depth = not self._show_depth
        self._btn_depth.config(
            text=f"Depth: {'ON' if self._show_depth else 'OFF'}",
            fg="#88f" if self._show_depth else "#666",
        )
        self._refresh_cameras()

    # -- Video feed -------------------------------------------------------

    def _video_loop(self) -> None:
        consecutive_errors = 0
        while self._running:
            if not self._frame_cb:
                time.sleep(1)
                continue
            try:
                frames = self._frame_cb()
                consecutive_errors = 0
                if not frames:
                    time.sleep(0.5)
                    continue

                new_images: dict[str, Image.Image] = {}
                new_depth: dict[str, Image.Image] = {}

                for source, (raw, rows, cols, fmt) in frames.items():
                    if "depth" in source:
                        if rows > 0 and cols > 0 and len(raw) == rows * cols * 2:
                            new_depth[source] = _depth_colormap(raw, rows, cols)
                    else:
                        try:
                            new_images[source] = Image.open(io.BytesIO(raw))
                        except Exception:
                            pass

                with self._lock:
                    self._live_images = new_images
                    self._live_depth = new_depth

                if self._root and self._running:
                    try:
                        self._root.after_idle(self._refresh_cameras)
                    except Exception:
                        pass

            except Exception:
                consecutive_errors += 1
                if consecutive_errors == 1 or consecutive_errors % 10 == 0:
                    _log.warning("Viewer video error (count=%d)", consecutive_errors, exc_info=True)
                time.sleep(min(consecutive_errors, 10))
                continue
            time.sleep(0.5)

    # -- Display ----------------------------------------------------------

    def _refresh_cameras(self) -> None:
        if not self._root or not self._running:
            return

        with self._lock:
            images = dict(self._live_images)
            depth = dict(self._live_depth)

        if not images:
            return

        ts = datetime.now().strftime("%H:%M:%S")
        depth_str = " +depth" if self._show_depth and depth else ""
        self._status_label.config(text=f"● LIVE{depth_str} | {ts}")

        self._photo_refs.clear()
        for i, source in enumerate(CAMERA_SOURCES):
            panel = self._panels[i]
            if source not in images:
                panel.config(image="", text="No signal")
                continue
            try:
                pw = max(panel.winfo_width(), 100)
                ph = max(panel.winfo_height(), 80)

                img = images[source].copy()
                rot = CAMERA_ROTATIONS.get(source)
                if rot:
                    img = img.rotate(rot, expand=True)

                if self._show_depth:
                    depth_source = DEPTH_SOURCES[i]
                    d = depth.get(depth_source)
                    if d:
                        d = d.copy()
                        drot = DEPTH_ROTATIONS.get(depth_source)
                        if drot:
                            d = d.rotate(drot, expand=True)
                        d = d.resize(img.size, Image.NEAREST)
                        if img.mode != "RGBA":
                            img = img.convert("RGBA")
                        img = Image.alpha_composite(img, d)

                img.thumbnail((pw, ph), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._photo_refs[source] = photo
                panel.config(image=photo, text="")
            except Exception:
                panel.config(image="", text="Error")

    def _schedule_bottom_refresh(self) -> None:
        if self._root and self._running:
            try:
                self._root.after_idle(self._refresh_bottom)
            except Exception:
                pass

    def _refresh_bottom(self) -> None:
        if not self._root or not self._running:
            return

        with self._lock:
            descs = list(self._desc_buffer)
            traces = list(self._trace_buffer)

        # Description pane
        desc_text = "\n".join(f"[{ts}] {d}" for ts, d in descs[-20:]) or "(waiting...)"
        self._desc_text.config(state=tk.NORMAL)
        self._desc_text.delete("1.0", tk.END)
        self._desc_text.insert("1.0", desc_text)
        self._desc_text.see(tk.END)
        self._desc_text.config(state=tk.DISABLED)

        # Trace pane
        trace_text = "\n".join(f"[{ts}] {t}" for ts, t in traces[-20:]) or "(no trace)"
        self._trace_text.config(state=tk.NORMAL)
        self._trace_text.delete("1.0", tk.END)
        self._trace_text.insert("1.0", trace_text)
        self._trace_text.see(tk.END)
        self._trace_text.config(state=tk.DISABLED)
