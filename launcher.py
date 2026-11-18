#!/usr/bin/env python3
"""
AI Lab Launcher — Multi-Service Dashboard
One-click launcher for Storm Server (port 8001) and Vision Server (port 8083) on WSL.
Thread-safe UI updates via root.after(). Terminal-only display (logs tab removed).
"""

import subprocess
import socket
import threading
import re
import customtkinter as ctk
import tkinter as tk

# ── Configuration ────────────────────────────────────────────────

WSL_DISTRO = "Ubuntu-24.04"
LLAMA_SERVER_PATH = "/home/allen/llama.cpp/build/bin/llama-server"

# ── JSON Persistence ────────────────────────────────────────────────
import json
import os as _os
import sys
import logging
import time as _time

# ── Logging Setup ────────────────────────────────────────────────
_LOG_DIR = "C:/Users/User/ai-lab-launcher/logs"
LOG_FILE = f"{_LOG_DIR}/launcher.log"

logger = logging.getLogger("Launcher")
logger.setLevel(logging.DEBUG)

# File handler — DEBUG level, detailed format
_fh = logging.FileHandler(LOG_FILE)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    "[%(asctime)s] [%(levelname)-8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))

# Console handler — INFO level, minimal format
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

logger.addHandler(_fh)
logger.addHandler(_ch)
# ──────────────────────────────────────────────────────────────────

_SERVICES_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "services.json")

def _load_services():
    """Load services from JSON, falling back to defaults if file missing/corrupt."""
    defaults = {
        "storm": {
            "name": "Storm Server", "port": 8001, "tmux_session": "storm_server",
            "log_file": "~/logs/storm.log",
            "command": "bash -c 'cd /home/allen/.openclaw/workspace/projects/the-storm && source venv/bin/activate && python3 web_server.py'"
        },
        "vision": {
            "name": "Vision Server", "port": 8083, "tmux_session": "vision_server",
            "log_file": "~/logs/vision.log",
            "command": f'{LLAMA_SERVER_PATH} -m ~/llama.cpp/models/Qwen_Qwen3-VL-8B-Instruct-Q6_K_L.gguf --mmproj ~/llama.cpp/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf --port 8083 --ctx-size 8192 -ngl 99 --flash-attn on'
        },
        "archivist": {
            "name": "Archivist (Qwen3.5-9B)", "port": 8081, "tmux_session": "archivist",
            "log_file": "~/logs/archivist.log",
            "command": f"CUDA_VISIBLE_DEVICES=0 {LLAMA_SERVER_PATH} -m ~/llama.cpp/models/Qwen3.5-9B-Q6_K.gguf --ctx-size 131072 -ngl 99 --jinja --flash-attn on --reasoning off --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 --presence-penalty 1.5 --repeat-penalty 1.0 -b 2048 -ub 1024 --host 127.0.0.1 --api-key-file ~/.config/llama/api.key --port 8081"
        },
        "embedding": {
            "name": "Embedding Server", "port": 8082, "tmux_session": "embedding_server",
            "log_file": "~/logs/embedding.log",
            "command": f"CUDA_VISIBLE_DEVICES=0 {LLAMA_SERVER_PATH} -m /home/allen/llama.cpp/models/nomic-embed-text-v1.5.Q8_0.gguf --alias nomic-embed --embedding --host 127.0.0.1 --api-key-file ~/.config/llama/api.key --port 8082 --ctx-size 32768 -b 8192 -ub 8192 --parallel 4 -ngl 99 --override-kv nomic-bert.context_length=int:8192 --rope-scaling yarn --rope-freq-scale 0.75"
        },
    }
    try:
        if _os.path.exists(_SERVICES_FILE):
            with open(_SERVICES_FILE, "r") as f:
                data = json.load(f)
            # Validate structure — merge any missing keys from defaults
            for k in defaults:
                if k not in data:
                    data[k] = defaults[k]
            return data
    except (json.JSONDecodeError, IOError):
        pass  # corrupt file → fall back to defaults
    return defaults

def _save_services():
    """Persist current SERVICES dict + SERVICE_ORDER order + standard selection to JSON."""
    try:
        payload = {
            "_order": SERVICE_ORDER,
            "_standard": list(_standard_services),
            **SERVICES
        }
        with open(_SERVICES_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except IOError as e:
        print(f"Failed to save services.json: {e}")

def _write_services_json(payload):
    """Write payload dict to services.json. Called by all save sites."""
    with open(_SERVICES_FILE, "w") as f:
        json.dump(payload, f, indent=2)

# Runtime data structures (populated by _load_services at module level)
SERVICES = {}  # populated below after _load_services call
SERVICE_ORDER = []  # populated below

# Populate SERVICES and SERVICE_ORDER from JSON (with defaults fallback)
_SERVICES_RAW = _load_services()

def _build_services():
    """Build SERVICES dict and SERVICE_ORDER list from loaded data."""
    global SERVICES, SERVICE_ORDER
    
    # Extract special keys first
    global _standard_services
    
    standard_keys = []
    if '_standard' in _SERVICES_RAW and isinstance(_SERVICES_RAW['_standard'], list):
        standard_keys = [k for k in _SERVICES_RAW['_standard'] if k in SERVICES or True]  # defer validation
    
    # Extract order array if present (stored as "_order" key in JSON)
    order_keys = []
    for k, v in _SERVICES_RAW.items():
        if k == '_order':
            order_keys = v
            break
    else:
        # No _order key — use dict insertion order
        order_keys = list(_SERVICES_RAW.keys())
    
    SERVICE_ORDER.clear()
    SERVICES.clear()
    
    for key in order_keys:
        svc = _SERVICES_RAW[key]
        if isinstance(svc, dict) and 'name' in svc:
            SERVICES[key] = svc
            if key not in SERVICE_ORDER:
                SERVICE_ORDER.append(key)
    
    # Set standard services (filter to only valid keys)
    _standard_services = [k for k in standard_keys if k in SERVICE_ORDER]
    # Fresh install or no saved favourites → all unchecked (empty list): "2cols" (2 columns, * rows) or "2rows" (* columns, 2 rows)
_LAYOUT_MODES = ["2cols", "2rows"]
_current_layout_idx = 0


_build_services()


class ServiceState:
    """Per-service runtime state."""
    def __init__(self):
        self.running = False
        self._starting = False
        self._collapsed = True  # collapsed when idle
        self._stop_event = threading.Event()
        self._log_refresh_stop = threading.Event()
        self.poll_thread = None
        self.log_refresh_thread = None


class LauncherApp:
    """Main launcher application with per-service UI blocks."""

    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.root = ctk.CTk()
        self.root.title("AI Lab Launcher")
        self.root.geometry("800x900")
        self.root.minsize(900, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Per-service runtime state and UI refs
        self.service_states = {key: ServiceState() for key in SERVICE_ORDER}
        self._service_ui_refs = {key: {} for key in SERVICE_ORDER}
        
        # Load saved layout mode from JSON
        if '_layout_mode' in _SERVICES_RAW and _SERVICES_RAW['_layout_mode'] in _LAYOUT_MODES:
            self._layout_mode = _SERVICES_RAW['_layout_mode']
            # Set global index to match loaded mode
            self._current_layout_idx = _LAYOUT_MODES.index(self._layout_mode)
        else:
            self._layout_mode = "2cols"
            self._current_layout_idx = 0

        # ── Main UI Layout ────────────────────────────────────────
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=16, pady=16)

        # ── GPU Status Strip (grid: left=gpu labels, right=profile buttons) ───
        self._gpu_labels = []
        gpu_strip = ctk.CTkFrame(main_frame, fg_color="transparent")
        gpu_strip.pack(fill="x", pady=(6, 0))
        gpu_strip.grid_columnconfigure(0, weight=1)
        gpu_strip.grid_columnconfigure(1, weight=0)

        # Left column: GPU labels
        gpu_frame = ctk.CTkFrame(gpu_strip, fg_color="transparent")
        gpu_frame.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        for idx in range(2):  # 2 GPUs
            gpu_label = ctk.CTkLabel(
                gpu_frame,
                text="--",
                font=ctk.CTkFont(family="Consolas", size=14),
                fg_color="#0d0d0d",
                bg_color="#0d0d0d",
            )
            gpu_label.pack(fill="x", pady=(1, 0))
            self._gpu_labels.append(gpu_label)

        # Right column: profile buttons
        btn_frame = ctk.CTkFrame(gpu_strip, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")
        self._btn_reorder = ctk.CTkButton(
            btn_frame,
            text="↻",
            font=ctk.CTkFont(size=18, weight="bold"),
            width=42,
            height=36,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=self._show_reorder_dialog,
        )
        self._btn_reorder.pack(side="left", padx=(0, 2))
        self._btn_standard = ctk.CTkButton(
            btn_frame,
            text="⭐",
            font=ctk.CTkFont(size=18, weight="bold"),
            width=42,
            height=36,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=self._start_standard_services,
        )
        self._btn_standard.pack(side="left", padx=(0, 2))
        self._btn_full = ctk.CTkButton(
            btn_frame,
            text="⊞",
            font=ctk.CTkFont(size=20, weight="bold"),
            width=42,
            height=36,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=self._cycle_layout_mode,
        )
        self._btn_full.pack(side="left", padx=(0, 2))
        self._btn_tailscale = ctk.CTkButton(
            btn_frame,
            text="🌐",
            font=ctk.CTkFont(size=18),
            width=42,
            height=36,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=self._show_tailscale_status,
        )
        self._btn_tailscale.pack(side="left", padx=(0, 2))
        self._btn_add = ctk.CTkButton(
            btn_frame,
            text="+",
            font=ctk.CTkFont(size=18, weight="bold"),
            width=42,
            height=36,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=self._show_add_service_dialog,
        )
        self._btn_add.pack(side="left")
        
        # Shutdown All & Close button
        self._btn_shutdown = ctk.CTkButton(
            btn_frame,
            text="⏻",
            font=ctk.CTkFont(size=18, weight="bold"),
            width=42,
            height=36,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=self._show_shutdown_dialog,
        )
        self._btn_shutdown.pack(side="left", padx=(4, 0))

        # Start GPU monitoring thread
        self._gpu_stop = threading.Event()
        self._gpu_thread = threading.Thread(target=self._poll_gpu, daemon=True)
        self._gpu_thread.start()

        # ── Service Area (non-scrollable container; panels stretch to fill space) ───
        service_area = ctk.CTkFrame(main_frame, fg_color="transparent")
        service_area.pack(fill="both", expand=True, pady=(6, 0))

        self._collapsed_zone = ctk.CTkFrame(service_area, fg_color="transparent")
        self._collapsed_zone.pack(fill="x", padx=4, pady=(4, 2))
        # Multi-row grid: max 4 strips per row

        self._expanded_zone = ctk.CTkFrame(service_area, fg_color="transparent")
        self._expanded_zone.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        for key in SERVICE_ORDER:
            self._build_service_block(key)

        # After UI is built, auto-detect already-running services and expand their panels
        self.root.after(500, self._auto_detect_running_services)


    def _auto_detect_running_services(self):
        """Check for existing tmux sessions on startup and expand panels for running services."""
        import subprocess as sp
        for key in SERVICE_ORDER:
            state = self.service_states[key]
            svc = SERVICES[key]
            refs = self._service_ui_refs.get(key)
            if not refs:
                continue

            # Check if tmux session exists
            result = sp.run(
                ["wsl", "-d", WSL_DISTRO, "--", "tmux", "has-session", "-t", svc["tmux_session"]],
                capture_output=True, encoding="utf-8", text=True, timeout=15,
            )
            if result.returncode == 0:
                # Session exists — mark as running and expand panel
                state.running = True
                refs["status_label"].configure(text="🟢 Running", text_color="#2d7d46")
                refs["toggle_btn"].configure(text="⏹  Stop", fg_color="#8b1e1e", hover_color="#a83232")
                # Start background threads for health polling and log refresh
                state._stop_event.clear()
                state.poll_thread = threading.Thread(target=self._health_poll, args=(key,), daemon=True)
                state.poll_thread.start()

                state._log_refresh_stop.clear()
                state.log_refresh_thread = threading.Thread(target=self._log_refresh_loop, args=(key,), daemon=True)
                state.log_refresh_thread.start()
                # Expand the panel after a short delay to let UI settle
                self.root.after(200, lambda k=key: self._toggle_collapse(k))

    def _poll_gpu(self):
        """Background thread: poll nvidia-smi every 2s."""
        while not self._gpu_stop.is_set():
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=index,name,fan.speed,temperature.gpu,power.draw,power.limit,memory.used,memory.total",
                     "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if result.returncode == 0:
                    lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                    # Sort by GPU index
                    gpu_data = []
                    for line in lines:
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 8:
                            def num(s):
                                """Extract first number from a string like '51 %' or '129.53 W'."""
                                if s == "N/A":
                                    return 0
                                import re
                                m = re.match(r'[\d.]+', s)
                                return int(m.group()) if m else 0
                            gpu_data.append({
                                "index": num(parts[0]),
                                "name": parts[1],
                                "fan": num(parts[2]),
                                "temp": num(parts[3]),
                                "pwr_used": float(parts[4].split()[0]) if parts[4] != "N/A" else 0.0,
                                "pwr_cap": float(parts[5].split()[0]) if parts[5] != "N/A" else 0.0,
                                "mem_used": num(parts[6]),
                                "mem_total": num(parts[7]) if num(parts[7]) > 0 else 1,
                            })

                    # Sort by index
                    gpu_data.sort(key=lambda x: x["index"])

                    # Update UI with sorted data
                    self.root.after(0, self._update_gpu_ui, gpu_data)

            except Exception:
                pass  # suppress poll errors

            self._gpu_stop.wait(0.5)

    def _update_gpu_ui(self, gpu_data):
        """Update GPU status labels with parsed data."""
        for idx, label in enumerate(self._gpu_labels):
            if idx < len(gpu_data):
                g = gpu_data[idx]
                text = f"GPU {g['index']} | Fan: {g['fan']}% | Temp: {g['temp']}°C | Pwr: {int(g['pwr_used'])}/{int(g['pwr_cap'])}W | Mem: {g['mem_used']}/{g['mem_total']}MB"
                label.configure(text=text)
            else:
                self._gpu_labels[idx].configure(text=f"GPU {idx}: --")

    def _build_service_block(self, key):
        """Build both a collapsed strip and an expanded panel for one service."""
        svc = SERVICES[key]
        refs = self._service_ui_refs[key]

        # ── Collapsed Strip (always visible) ────────────────────────
        refs["strip_frame"] = ctk.CTkFrame(
            self._collapsed_zone, fg_color="#1a1a1a", border_width=1, border_color="#2a2a2a"
        )
        # Calculate row/column for wrapping: max 4 per row
        idx = SERVICE_ORDER.index(key)
        strip_row = idx // 4
        strip_col = idx % 4
        
        # Configure this row if it doesn't exist yet
        num_cols = min(4, len(SERVICE_ORDER) - (strip_row * 4))
        for c in range(num_cols):
            self._collapsed_zone.grid_columnconfigure(c, weight=1)
        
        refs["strip_frame"].grid(row=strip_row, column=strip_col, sticky="ew", padx=2, pady=2)

        # Header row inside strip
        strip_header = ctk.CTkFrame(refs["strip_frame"], fg_color="transparent")
        strip_header.pack(fill="x", padx=8, pady=4)

        # Status dot on strip (left)
        refs["status_label"] = ctk.CTkLabel(
            strip_header,
            text="⚫",
            font=ctk.CTkFont(size=12),
            text_color="#8b1e1e",
        )
        refs["status_label"].pack(side="left", padx=(0, 6))

        # Title on strip (center-ish)
        title_label = ctk.CTkLabel(
            strip_header,
            text=svc['name'],
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        title_label.pack(side="left")

        # Expand button (▶) on the right
        refs["collapse_btn"] = ctk.CTkButton(
            strip_header,
            text="▶",
            font=ctk.CTkFont(size=12),
            width=32,
            height=28,
            fg_color="#2d7d46",
            hover_color="#3a9e5a",
            text_color="white",
            corner_radius=4,
            command=lambda k=key: self._toggle_collapse(k),
        )
        refs["collapse_btn"].pack(side="right")

        # ── Expanded Panel (hidden initially) ───────────────────────
        refs["panel_frame"] = ctk.CTkFrame(
            self._expanded_zone, fg_color="#1a1a1a", border_width=1, border_color="#2a2a2a"
        )
        # Grid on panel_frame so content fills available cell width
        refs["panel_frame"].grid_rowconfigure(0, weight=1)
        refs["panel_frame"].grid_columnconfigure(0, weight=1)

        # Content wrapper — expands to fill the grid cell; uses grid internally for its children
        refs["panel_content"] = ctk.CTkFrame(
            refs["panel_frame"], fg_color="transparent"
        )
        refs["panel_content"].grid_rowconfigure(0, weight=0)  # header row
        refs["panel_content"].grid_rowconfigure(1, weight=0)  # buttons row
        refs["panel_content"].grid_rowconfigure(2, weight=1)  # log area (fills remaining)
        refs["panel_content"].grid_columnconfigure(0, weight=1)
        refs["panel_content"].grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Header row inside panel
        panel_header = ctk.CTkFrame(refs["panel_content"], fg_color="transparent")
        panel_header.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        panel_header.grid_columnconfigure(1, weight=1)

        # ── Title on panel ────────────────────────────────────────
        title_label2 = ctk.CTkLabel(
            panel_header,
            text=svc['name'],
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        title_label2.pack(side="left")

        # Collapse button (▼) on right
        refs["collapse_btn_panel"] = ctk.CTkButton(
            panel_header,
            text="▼",
            font=ctk.CTkFont(size=10),
            width=32,
            height=28,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=lambda k=key: self._toggle_collapse(k),
        )
        refs["collapse_btn_panel"].pack(side="right")

        # Status on panel
        refs["status_label_panel"] = ctk.CTkLabel(
            panel_header,
            text="⚫ Stopped",
            font=ctk.CTkFont(size=11),
            text_color="#8b1e1e",
        )

        # Detail line on panel
        detail_label = ctk.CTkLabel(
            panel_header,
            text=f"Port {svc['port']}  |  tmux: {svc['tmux_session']}",
            font=ctk.CTkFont(size=10),
            text_color="#666",
        )

        # Separator between detail and status
        sep = ctk.CTkLabel(
            panel_header,
            text=" | ",
            font=ctk.CTkFont(size=10),
            text_color="#666",
        )

        # Pack right-to-left: collapse (already there), status, sep, detail
        refs["status_label_panel"].pack(side="right", padx=(0, 16))
        sep.pack(side="right", padx=(6, 0))
        detail_label.pack(side="right", padx=(6, 0))


        # Start/Stop + Edit/Delete button row
        btn_frame = ctk.CTkFrame(refs["panel_content"], fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 4))
        refs["toggle_btn"] = ctk.CTkButton(
            btn_frame,
            text="▶  Start",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=170,
            height=32,
            fg_color="#2d7d46",
            hover_color="#3a9e5a",
            text_color="white",
            command=lambda k=key: self._toggle_service(k),
        )
        refs["toggle_btn"].pack(side="left")

        # Edit button (visible only when expanded)
        refs["edit_btn"] = ctk.CTkButton(
            btn_frame,
            text="    ✏️",
            font=ctk.CTkFont(size=16),
            width=32,
            height=32,
            fg_color="#c4a20d",
            hover_color="#e0be15",
            text_color="white",
            corner_radius=4,
            command=lambda k=key: self._show_edit_service_dialog(k),
        )
        refs["edit_btn"].pack(side="left", padx=(6, 3))

        # Delete button (visible only when expanded)
        refs["delete_btn"] = ctk.CTkButton(
            btn_frame,
            text="    🗑️",
            font=ctk.CTkFont(size=16),
            width=32,
            height=32,
            fg_color="#c43a3a",
            hover_color="#d95050",
            text_color="white",
            corner_radius=4,
            command=lambda k=key: self._confirm_delete_service(k),
        )
        refs["delete_btn"].pack(side="left", padx=(3, 3))

        # Kill button (visible only when expanded)
        refs["kill_btn"] = ctk.CTkButton(
            btn_frame,
            text="    ☠️",
            font=ctk.CTkFont(size=16),
            width=32,
            height=32,
            fg_color="#555555",
            hover_color="#707070",
            text_color="#ff6b6b",
            corner_radius=4,
            command=lambda k=key: self._kill_service_process(k),
        )
        refs["kill_btn"].pack(side="left", padx=(3, 0))


        # Log panel container (inside expanded panel only)
        log_container = ctk.CTkFrame(refs["panel_content"], fg_color="#1a1a1a")
        log_container.grid(row=2, column=0, sticky="nsew", padx=8, pady=(2, 6))

        log_text_frame = ctk.CTkFrame(log_container, fg_color="transparent")
        log_text_frame.pack(fill="both", expand=True)
        log_text_frame.grid_columnconfigure(0, weight=1)
        log_text_frame.grid_rowconfigure(0, weight=1)

        # Terminal-only textbox (no tabs) — CTkTextbox has built-in scrollbars (activate_scrollbars=True default)
        refs["log_text"] = ctk.CTkTextbox(
            log_text_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            state="disabled",
            wrap="char",
            fg_color="#0d0d0d",
            text_color="#cccccc",
            corner_radius=4,
        )
        refs["log_text"].grid(row=0, column=0, sticky="nsew")

        # Right-click context menu for terminal textbox
        self._setup_context_menu(refs["log_text"], key)

        # Toolbar row (Detach + Dock)
        toolbar = ctk.CTkFrame(log_container, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 6))

        refs["detach_btn"] = ctk.CTkButton(
            toolbar,
            text="📌 Detach",
            font=ctk.CTkFont(size=10),
            width=80,
            height=24,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=lambda k=key: self._toggle_floating_log(k),
        )
        refs["detach_btn"].pack(side="left")

        # ── Store refs ────────────────────────────────────────────
        refs["_current_tab"] = "terminal"
        refs["log_window"] = None
        refs["_collapsed"] = True  # Start collapsed

    def _setup_context_menu(self, text_widget, key):
        """Set up right-click context menu for a textbox."""
        import tkinter as tk
        menu = tk.Menu(text_widget, tearoff=0, bg="#2d2d2d", fg="#cccccc",
                       activebackground="#444", activeforeground="white",
                       font=("Consolas", 9), bd=1, relief="flat")
        copy_cmd = lambda: self._copy_selection(text_widget, key)
        menu.add_command(label="Copy", command=copy_cmd)

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        text_widget.bind("<Button-3>", show_menu)

    def _copy_selection(self, text_widget, key):
        """Copy selected text to clipboard."""
        try:
            # Get the underlying tk.Text widget from CTkTextbox wrapper
            if hasattr(text_widget, '_textbox'):
                widget = text_widget._textbox
            else:
                widget = text_widget
            selection = widget.get("sel.first", "sel.last")
            if selection:
                self.root.clipboard_clear()
                self.root.clipboard_append(selection.strip())
        except Exception:
            pass

    def _toggle_floating_log(self, key):
        """Toggle log panel between detached (floating) and docked (inline) states."""
        refs = self._service_ui_refs[key]

        if refs["log_window"] is not None:
            # ── DOCK path: destroy floating, restore inline ──────────────
            try:
                refs["log_window"].destroy()
            except Exception:
                pass
            refs["log_window"] = None
            refs["float_text"] = None
            refs["dock_btn"] = None
            return

        # ── DETACH path: create floating window ────────────────────────
        log_window = ctk.CTkToplevel(self.root)
        log_window.title(f"{SERVICES[key]['name']} — Terminal")
        log_window.geometry("700x450")
        log_window.minsize(400, 200)
        log_window.protocol("WM_DELETE_WINDOW", lambda: self._toggle_floating_log(key))

        # Floating toolbar
        float_toolbar = ctk.CTkFrame(log_window, fg_color="transparent")
        float_toolbar.pack(fill="x", padx=8, pady=(8, 4))

        dock_btn = ctk.CTkButton(
            float_toolbar,
            text="📌 Dock",
            font=ctk.CTkFont(size=10),
            width=80,
            height=24,
            fg_color="#333",
            hover_color="#555",
            text_color="#aaa",
            corner_radius=4,
            command=lambda k=key: self._toggle_floating_log(k),
        )
        dock_btn.pack(side="left")

        # Floating textbox (same as inline)
        float_text = ctk.CTkTextbox(
            log_window,
            font=ctk.CTkFont(family="Consolas", size=11),
            state="disabled",
            wrap="char",
            fg_color="#0d0d0d",
            text_color="#cccccc",
        )
        float_text.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        # Right-click menu for floating textbox
        import tkinter as tk
        float_menu = tk.Menu(float_text, tearoff=0, bg="#2d2d2d", fg="#cccccc",
                             activebackground="#444", activeforeground="white",
                             font=("Consolas", 9), bd=1, relief="flat")
        float_copy_cmd = lambda: self._copy_selection(float_text, key)
        float_menu.add_command(label="Copy", command=float_copy_cmd)

        def show_float_menu(event):
            try:
                float_menu.tk_popup(event.x_root, event.y_root)
            finally:
                float_menu.grab_release()

        float_text.bind("<Button-3>", show_float_menu)

        # Store refs
        refs["log_window"] = log_window
        refs["float_text"] = float_text
        refs["dock_btn"] = dock_btn

    # ── Tab Switching (no-op — always terminal) ────────────────────

    def _switch_tab(self, key, tab_name):
        """Always show terminal — logs tab removed."""
        pass

    # ── Log Refresh & Terminal Capture ─────────────────────────────

    def _refresh_logs(self, key):
        """Update the log panel with current terminal capture for a service."""
        refs = self._service_ui_refs.get(key)
        if not refs:
            return

        svc = SERVICES[key]
        content = self._capture_terminal(svc)

        # Update inline textbox — diff-based: only rewrite if content actually changed
        tb = refs["log_text"]
        try:
            current = tb.get("1.0", "end-1c")
            # Never overwrite real log content with dead-state placeholders
            dead_placeholders = [
                "(empty session",
                "(timeout reading terminal)",
                "(tmux not available",
                "(error:",
                "(unable to read log)",
                "(empty)",
            ]
            is_placeholder = any(p in content for p in dead_placeholders)
            if is_placeholder and current.strip() and not any(p in current for p in dead_placeholders):
                return  # keep existing real content

            # Skip if content hasn't changed (avoids flicker + wasted CPU)
            if current == content:
                return

            tb.configure(state="normal")
            tb.delete("1.0", "end")
            tb.insert("1.0", content)
            tb.see("end")  # auto-scroll to bottom
            tb.configure(state="disabled")
        except Exception:
            pass

        # Update floating textbox if detached — diff-based skip like inline
        float_text = refs.get("float_text")
        if float_text is not None:
            try:
                current_f = float_text.get("1.0", "end-1c")
                is_placeholder = any(p in content for p in dead_placeholders)
                if is_placeholder and current_f.strip() and not any(p in current_f for p in dead_placeholders):
                    pass  # keep existing real content
                elif current_f == content:
                    pass  # skip rewrite if unchanged (avoids flicker + CPU waste)
                else:
                    float_text.configure(state="normal")
                    float_text.delete("1.0", "end")
                    float_text.insert("1.0", content)
                    float_text.see("end")
                    float_text.configure(state="disabled")
            except Exception:
                pass

    def _capture_terminal(self, svc: dict, lines=200) -> str:
        """Capture the visible pane from a tmux session."""
        try:
            result = subprocess.run(
                ["wsl", "-d", WSL_DISTRO, "--", "tmux", "capture-pane", "-t", svc["tmux_session"], "-J", "-p", "-S", f"-{lines}"],
                capture_output=True,
                encoding="utf-8",
                text=True,
                timeout=3,
            )
            # Strip ANSI escape sequences (clear-screen codes from dying process)
            output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", result.stdout)
            output = output.strip()
            return output if output else "(empty session — service not running?)"
        except subprocess.TimeoutExpired:
            return "(timeout reading terminal)"
        except FileNotFoundError:
            return "(tmux not available in WSL)"
        except Exception as e:
            return f"(error: {e})"

    # ── UI Update Helpers ────────────────────────────────────────

    def _update_starting_ui(self, key):
        """Show 'Starting...' state immediately when user clicks Start."""
        refs = self._service_ui_refs.get(key)
        if not refs:
            return
        refs["status_label"].configure(text="⏳", text_color="#e6a800")
        if "status_label_panel" in refs:
            refs["status_label_panel"].configure(text="⏳ Starting...", text_color="#e6a800")
        refs["toggle_btn"].configure(text="⏳  Starting...", fg_color="#e6a800", hover_color="#c49200")

    def _update_service_ui(self, key, running: bool):
        """Thread-safe UI update for a specific service."""
        refs = self._service_ui_refs.get(key)
        if not refs:
            return

        state = self.service_states[key]
        svc = SERVICES[key]

        # While still starting up, never flip back to "Stopped"
        # Stay on "Starting..." until healthy or failed
        if not running and state._starting:
            return

        state.running = running
        state._starting = False

        if running:
            refs["status_label"].configure(text="🟢", text_color="#2d7d46")
            if "status_label_panel" in refs:
                refs["status_label_panel"].configure(text="🟢 Running", text_color="#2d7d46")
            refs["toggle_btn"].configure(text="⏹  Stop", fg_color="#8b1e1e", hover_color="#a83232")
        else:
            refs["status_label"].configure(text="⚫", text_color="#8b1e1e")
            if "status_label_panel" in refs:
                refs["status_label_panel"].configure(text="⚫ Stopped", text_color="#8b1e1e")
            refs["toggle_btn"].configure(text="▶  Start", fg_color="#2d7d46", hover_color="#3a9e5a")


        # Refresh logs on any state change
        self._refresh_logs(key)

    def _expand_service(self, key):
        """Expand a collapsed service block — add panel to grid."""
        state = self.service_states[key]
        refs = self._service_ui_refs.get(key)
        if not refs or not state._collapsed:
            return
        state._collapsed = False
        refs["panel_frame"].grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._recalc_layout()

    def _expand_services_batch(self, keys):
        """Expand multiple service blocks at once, then recalculate grid positions once."""
        for key in keys:
            state = self.service_states[key]
            refs = self._service_ui_refs.get(key)
            if not refs or state._collapsed:
                continue
            state._collapsed = False
            refs["panel_frame"].grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._recalc_layout()

    def _collapse_service(self, key):
        """Collapse an expanded service block — remove panel from grid."""
        state = self.service_states[key]
        refs = self._service_ui_refs.get(key)
        if not refs or state._collapsed:
            return
        state._collapsed = True
        refs["panel_frame"].grid_remove()
        self._recalc_layout()

    def _cycle_layout_mode(self):
        """Cycle between layout modes: 2 columns ↔ 2 rows."""
        global _current_layout_idx
        _current_layout_idx = (_current_layout_idx + 1) % len(_LAYOUT_MODES)
        self._layout_mode = _LAYOUT_MODES[_current_layout_idx]
        
        # Save to JSON
        try:
            payload = {}
            for key in SERVICE_ORDER:
                if key in SERVICES:
                    payload[key] = SERVICES[key]
            payload["_order"] = list(SERVICE_ORDER)
            payload["_layout_mode"] = self._layout_mode
            
            _write_services_json(payload)
        except IOError:
            pass
        
        # Recalculate layout to apply new mode
        self._recalc_layout()

    def _recalc_layout(self):
        """Recalculate grid positions for expanded panels.
        
        Pure grid layout — no mixing with pack.
        1 column if ≤2 open, 2 columns if >2.
        Row weights ensure equal vertical distribution.
        """
        refs_list = [self._service_ui_refs[k] for k in SERVICE_ORDER if not self.service_states[k]._collapsed]
        num_open = len(refs_list)

        if num_open == 0:
            # Hide all panels, clear grid rows
            for key in SERVICE_ORDER:
                refs = self._service_ui_refs[key]
                try:
                    refs["panel_frame"].grid_remove()
                except Exception:
                    pass
            return

        # Determine layout mode
        if not hasattr(self, '_layout_mode'):
            self._layout_mode = "2cols"  # default
        
        if num_open == 0:
            return
        elif self._layout_mode == "2rows":
            # Max 2 rows, * columns (horizontal spread)
            rows = 2
            cols = (num_open + rows - 1) // rows  # ceiling division
        else:
            # Default: up to 2 columns, * rows (vertical stack)
            cols = min(2, num_open)

        # Clear all existing column/row configs to avoid stale constraints
        for c in range(self._expanded_zone.grid_size()[0]):
            self._expanded_zone.grid_columnconfigure(c, weight=0)
        for r in range(self._expanded_zone.grid_size()[1]):
            self._expanded_zone.grid_rowconfigure(r, weight=0)
        
        # Configure columns dynamically based on layout mode
        for c in range(cols):
            self._expanded_zone.grid_columnconfigure(c, weight=1)

        # Calculate rows needed and configure weights for equal distribution
        if self._layout_mode == "2rows":
            # 2 rows fixed, calculate actual rows (max 2)
            rows_needed = min(2, num_open)
        else:
            # 2 columns fixed, calculate rows
            rows_needed = (num_open + cols - 1) // cols
        for r in range(rows_needed):
            self._expanded_zone.grid_rowconfigure(r, weight=1)

        # Position each panel in the grid
        for idx, refs in enumerate(refs_list):
            if self._layout_mode == "2rows":
                # 2 rows, fill left-to-right then top-to-bottom
                row = idx % 2
                col = idx // 2
            else:
                # 2 columns, fill top-to-bottom then left-to-right
                row = idx // cols
                col = idx % cols
            try:
                refs["panel_frame"].grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            except Exception:
                pass

    def _update_shutdown_ui(self, key, remaining):
        """Update status with shutdown progress message."""
        refs = self._service_ui_refs.get(key)
        if not refs:
            return
        refs["status_label"].configure(text=f"⏳ ({remaining}s)", text_color="#e6a800")
        if "status_label_panel" in refs:
            refs["status_label_panel"].configure(text=f"⏳ Stopping... ({remaining}s)", text_color="#e6a800")
        refs["toggle_btn"].configure(text="⏳  Stopping...", fg_color="#e6a800", hover_color="#c49200")

    # ── Health Poll & Log Refresh Loops ─────────────────────────

    def _health_poll(self, key):
        """Background polling thread — checks health and schedules UI updates."""
        state = self.service_states[key]
        svc = SERVICES[key]

        while not state._stop_event.is_set():
            try:
                is_healthy = self._check_health(svc)
                self.root.after(0, self._update_service_ui, key, is_healthy)
            except Exception as e:
                self.root.after(0, lambda k=key: (
                    self._service_ui_refs.get(k, {}).get("status_label").configure(
                        text="⚠️ Monitor Error", text_color="#ffaa00"
                    ) if k in self._service_ui_refs else None
                ))
                logger.error("[HEALTH_POLL] Thread crashed for %s: %s", key, e)
            state._stop_event.wait(2)

    def _log_refresh_loop(self, key):
        """Background thread: continuously refresh logs from service start until stop."""
        state = self.service_states[key]
        while not state._log_refresh_stop.is_set():
            try:
                self.root.after(0, self._refresh_logs, key)
            except Exception as e:
                self.root.after(0, lambda k=key: (
                    self._service_ui_refs.get(k, {}).get("status_label").configure(
                        text="⚠️ Log Error", text_color="#ffaa00"
                    ) if k in self._service_ui_refs else None
                ))
                logger.error("[LOG_REFRESH] Thread crashed for %s: %s", key, e)
            state._log_refresh_stop.wait(1)

    def _check_health(self, svc: dict) -> bool:
        """Check if the service is healthy.
        
        For port > 0: checks TCP socket connectivity.
        For port == 0 (process-only): checks tmux session is alive.
        """
        if svc.get("port", 0) == 0:
            # Process-only service — just check tmux session exists
            try:
                result = subprocess.run(
                    ["wsl", "-d", WSL_DISTRO, "--", "tmux", "has-session",
                     "-t", svc["tmux_session"]],
                    capture_output=True, encoding="utf-8", text=True,
                )
                return result.returncode == 0
            except Exception:
                return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex(("127.0.0.1", svc["port"]))
            sock.close()
            return result == 0
        except Exception:
            return False

    # ── Profile Buttons (placeholder for Phase 1) ──────────────

    def _start_standard_services(self):
        """Show favourites selection dialog, then start selected ones."""
        global _standard_services
        
        # Create fresh dialog each time (avoids stale Toplevel issues)
        self._std_dialog = ctk.CTkToplevel(self.root)
        self._std_dialog.title("Select Favourites")
        self._std_dialog.geometry("400x500")
        self._std_dialog.resizable(False, False)
        self._std_dialog.grab_set()
        self._std_dialog.transient(self.root)

        # Center on main window
        x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 500) // 2
        self._std_dialog.geometry(f"+{x}+{y}")

        def on_close():
            if hasattr(self, "_std_dialog") and self._std_dialog.winfo_exists():
                self._std_dialog.destroy()
        self._std_dialog.protocol("WM_DELETE_WINDOW", on_close)

        # Select All / Deselect All row
        sel_frame = ctk.CTkFrame(self._std_dialog, fg_color="transparent")
        sel_frame.pack(fill="x", padx=12, pady=(8, 4))
        
        ctk.CTkButton(sel_frame, text="Select All", font=ctk.CTkFont(size=12),
                      fg_color="#2d7d46", hover_color="#3a9e5a",
                      text_color="white", corner_radius=4,
                      width=100, height=32,
                      command=lambda: [var.set(1) for var in self._std_vars.values()]).pack(side="left", padx=(4, 2))
        ctk.CTkButton(sel_frame, text="Deselect All", font=ctk.CTkFont(size=12),
                      fg_color="#8b4513", hover_color="#a0522d",
                      text_color="white", corner_radius=4,
                      width=100, height=32,
                      command=lambda: [var.set(0) for var in self._std_vars.values()]).pack(side="left", padx=(2, 4))

        # Scrollable frame for checkboxes
        scroll = ctk.CTkScrollableFrame(self._std_dialog, width=376, height=380)
        scroll.pack(pady=4, padx=12, expand=True, fill="both")

        self._std_vars = {}  # key -> IntVar

        for idx, key in enumerate(SERVICE_ORDER):
            svc = SERVICES.get(key, {})
            name = svc.get("name", key)
            running = self.service_states[key].running
            
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=1, padx=4)

            var = ctk.IntVar(value=1 if key in _standard_services else 0)
            self._std_vars[key] = var

            # Checkbox
            chk = ctk.CTkCheckBox(
                row, text=f" {name}",
                variable=var, font=ctk.CTkFont(size=11),
                width=280,
            )
            # Fix: CTkCheckBox ignores IntVar(value=1) at init — force sync
            if var.get():
                chk.select()
            if running:
                chk.configure(state="disabled", text=f" {name} (running)", fg_color="#555")
            chk.pack(side="left", padx=(4, 0))

            # Status indicator
            status = "●" if running else "○"
            color = "#4caf50" if running else "#888"
            lbl = ctk.CTkLabel(
                row, text=f" {status}", font=ctk.CTkFont(size=12),
                text_color=color,
            )
            lbl.pack(side="left", padx=(2, 0))

        # Start button row
        btn_row = ctk.CTkFrame(self._std_dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(4, 8))

        def on_start():
            """Start selected services (checked, non-running) and save selection."""
            selected = [k for k, v in self._std_vars.items() if v.get() == 1]
            
            # Save the selection first
            global _standard_services
            _standard_services = selected
            try:
                payload = {
                    "_order": SERVICE_ORDER,
                    "_standard": selected,
                    **SERVICES
                }
                _write_services_json(payload)
            except IOError:
                pass

            started = []
            failed = []
            for key in selected:
                if self.service_states[key].running:
                    continue  # skip already running
                success = self._start_service(key)
                if success:
                    started.append(key)
                else:
                    failed.append(key)

            # Expand only (don't toggle — skip if already expanded)
            def _expand_if_collapsed(key):
                state = self.service_states[key]
                refs = self._service_ui_refs.get(key)
                if not refs or not state._collapsed:
                    return  # already expanded or no refs
                state._collapsed = False
                refs["panel_frame"].grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
                refs["collapse_btn"].configure(text="▼")
                if "collapse_btn_panel" in refs:
                    refs["collapse_btn_panel"].configure(text="▲")
                refs["edit_btn"].pack(side="left", padx=(6, 3))
                refs["delete_btn"].pack(side="left", padx=(3, 3))
                refs["kill_btn"].pack(side="left", padx=(3, 0))
                self._recalc_layout()

            for key in started:
                self.root.after(0, lambda k=key: _expand_if_collapsed(k))

            # Show result message
            msg_parts = []
            if started:
                msg_parts.append(f"✅ Started: {', '.join(started)}")
            if failed:
                msg_parts.append(f"❌ Failed: {', '.join(failed)}")
            
            if not started and not failed:
                msg = "All selected services are already running."
            elif msg_parts:
                msg = "\n".join(msg_parts)
            else:
                msg = "No services were selected."

            self._std_dialog.destroy()

        def on_save():
            """Save current checkbox selection as favourites. Dialog stays open."""
            global _standard_services
            selected = [k for k, v in self._std_vars.items() if v.get() == 1]
            _standard_services = selected
            
            try:
                payload = {
                    "_order": SERVICE_ORDER,
                    "_standard": selected,
                    **SERVICES
                }
                _write_services_json(payload)
            except IOError:
                pass

        # Start button (green) — launches selected services
        ctk.CTkButton(btn_row, text="Start", font=ctk.CTkFont(size=12, weight="bold"),
                      fg_color="#2d7d46", hover_color="#3a9e5a",
                      text_color="white", corner_radius=4,
                      width=100, height=32,
                      command=on_start).pack(side="left", padx=(4, 2))

        # Save button (blue) — saves selection only
        ctk.CTkButton(btn_row, text="Save", font=ctk.CTkFont(size=12),
                      fg_color="#1565c0", hover_color="#1976d2",
                      text_color="white", corner_radius=4,
                      width=100, height=32,
                      command=on_save).pack(side="left", padx=(2, 2))

        # Close button (grey) — closes dialog
        ctk.CTkButton(btn_row, text="Close", font=ctk.CTkFont(size=12),
                      fg_color="#555", hover_color="#666",
                      text_color="white", corner_radius=4,
                      width=100, height=32,
                      command=lambda: self._std_dialog.destroy()).pack(side="left", padx=(2, 4))

    def _start_all_services(self):
        """Start all services preset."""
        pass  # TODO: wire to full service set

    def _copy_from(self, widget, event):
        """Copy text from the given widget. Called from context menu."""
        try:
            if isinstance(widget, (tk.Entry, ctk.CTkEntry)):
                text = widget.get()
            elif isinstance(widget, (tk.Text, ctk.CTkTextbox)):
                # Try to get selected text first, fall back to all
                try:
                    text = widget.get("sel.first", "sel.last")
                except tk.TclError:
                    text = widget.get("1.0", "end-1c")
            else:
                return
            if text:
                widget.clipboard_clear()
                widget.clipboard_append(text)
        except tk.TclError:
            pass

    def _paste_into(self, widget, event):
        """Paste clipboard content into the given widget. Called from menu."""
        try:
            text = widget.clipboard_get()
            
            # CTkEntry/CTkTextbox wrap internal tk widgets — event.widget is the real one
            if isinstance(widget, (tk.Entry, ctk.CTkEntry)):
                widget.delete(0, "end")
                widget.insert(0, text)
            elif isinstance(widget, (tk.Text, ctk.CTkTextbox)):
                widget.insert("insert", text)
        except tk.TclError:
            pass  # clipboard empty or not text

    def _show_ctx(self, event):
        """Show context menu at click position."""
        widget = event.widget
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Copy", command=lambda w=widget: self._copy_from(w, event))
        menu.add_command(label="Paste", command=lambda w=widget: self._paste_into(w, event))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.after_idle(menu.unpost)

    def _show_reorder_dialog(self):
        """Modal dialog to reorder services via up/down arrows."""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Reorder Services")
        dialog.geometry("350x400")
        dialog.grab_set()
        dialog.transient(self.root)
        dialog.focus_set()

        # Center on root
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 350) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 400) // 2
        dialog.geometry(f"+{x}+{y}")

        # Working copy of order
        order_list = list(SERVICE_ORDER)

        # Bottom buttons (outside scroll frame so rebuild doesn't destroy them)
        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom", pady=(0, 8))

        # Scrollable frame for the list
        scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        btn_refs = []  # keep refs to arrow buttons

        def update_buttons():
            """Enable/disable arrows based on position."""
            for i, (btn_up, btn_down) in enumerate(btn_refs):
                btn_up.configure(state="normal" if i > 0 else "disabled")
                btn_down.configure(state="normal" if i < len(order_list) - 1 else "disabled")

        def move_up(idx):
            order_list[idx], order_list[idx-1] = order_list[idx-1], order_list[idx]
            rebuild_list()

        def move_down(idx):
            order_list[idx], order_list[idx+1] = order_list[idx+1], order_list[idx]
            rebuild_list()

        def rebuild_list():
            # Clear existing widgets
            for w in scroll.winfo_children():
                w.destroy()
            btn_refs.clear()

            for i, key in enumerate(order_list):
                row = ctk.CTkFrame(scroll, fg_color="#1a1a1a")
                row.pack(fill="x", pady=2)

                # Name label
                name = SERVICES[key]["name"] if key in SERVICES else key
                lbl = ctk.CTkLabel(row, text=f"  {name}", font=ctk.CTkFont(size=12), anchor="w")
                lbl.pack(side="left", fill="x", expand=True, padx=4)

                # Up/Down arrows
                up_btn = ctk.CTkButton(
                    row, text="⬆", width=32, height=28,
                    font=ctk.CTkFont(size=14),
                    fg_color="#333", hover_color="#555",
                    text_color="#aaa", corner_radius=3,
                    command=lambda i=i: move_up(i),
                )
                up_btn.pack(side="left")

                down_btn = ctk.CTkButton(
                    row, text="⬇", width=32, height=28,
                    font=ctk.CTkFont(size=14),
                    fg_color="#333", hover_color="#555",
                    text_color="#aaa", corner_radius=3,
                    command=lambda i=i: move_down(i),
                )
                down_btn.pack(side="left", padx=(2, 0))

                btn_refs.append((up_btn, down_btn))

            update_buttons()

        rebuild_list()

        def on_save():
            SERVICE_ORDER.clear()
            SERVICE_ORDER.extend(order_list)
            # Save to JSON
            try:
                payload = {}
                for k in SERVICE_ORDER:
                    if k in SERVICES:
                        payload[k] = SERVICES[k]
                payload["_order"] = list(SERVICE_ORDER)
                payload["_layout_mode"] = getattr(self, '_layout_mode', "2cols")
                payload["_standard"] = list(_standard_services) if '_standard_services' in dir() else []
                _write_services_json(payload)
            except IOError:
                pass
            # Rebuild UI
            self._rebuild_all_service_blocks()
            dialog.destroy()

        ctk.CTkButton(btn_row, text="Save", font=ctk.CTkFont(size=12, weight="bold"),
                      fg_color="#2d7d46", hover_color="#3a9e5a",
                      text_color="white", corner_radius=4,
                      width=100, height=32,
                      command=on_save).pack(side="left", padx=(4, 2))
        ctk.CTkButton(btn_row, text="Cancel", font=ctk.CTkFont(size=12),
                      fg_color="#555", hover_color="#777",
                      text_color="white", corner_radius=4,
                      width=100, height=32,
                      command=dialog.destroy).pack(side="left", padx=(2, 4))


    def _show_tailscale_status(self):
        """Dialog to manage Storm's Tailscale Funnel (public URL)."""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Tailscale Funnel")
        dialog.geometry("480x320")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.transient(self.root)
        dialog.focus_set()

        # Center on root
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 480) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 320) // 2
        dialog.geometry(f"+{x}+{y}")

        # ── State tracking ──────────────────────────────────────────────
        funnel_active = [False]
        funnel_url = [""]

        def update_buttons():
            """Update button states based on current funnel status."""
            if not funnel_active[0]:
                btn_activate.configure(state="normal")
                btn_deactivate.configure(state="disabled")
            else:
                btn_activate.configure(state="disabled")
                btn_deactivate.configure(state="normal")

        def check_status():
            """Check if funnel is currently active via tailscale CLI."""
            try:
                # Use 'tailscale funnel status' — it reliably outputs 'Funnel on:' or 'No serve config'
                result = subprocess.run(
                    ["wsl", "-d", WSL_DISTRO, "--", "tailscale", "funnel", "status"],
                    capture_output=True, encoding="utf-8", text=True, timeout=8,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    # Status check failed — default to INACTIVE
                    self.root.after(0, _on_status_done)
                    return

                output = result.stdout.strip()
                if "Funnel on" in output:
                    funnel_active[0] = True
                    # Extract URL from funnel status output (lines like '- https://...' or '# Funnel on:')
                    url_match = re.search(r'https?://[^\s)]+', output)
                    if url_match:
                        funnel_url[0] = url_match.group(0)
                else:
                    funnel_active[0] = False

            except Exception:
                # WSL not available, tailscale not installed, etc.
                # Default to INACTIVE — safe fallback
                pass
            finally:
                # Always update UI after check completes (success or failure)
                self.root.after(0, _on_status_done)

        def _on_status_done():
            """Callback from background thread after status check."""
            if funnel_active[0]:
                status_label.configure(text="✅ Funnel is ACTIVE", text_color="#4caf50")
                url_label.configure(text=funnel_url[0] or "URL not available", text_color="#4fc3f7")
            else:
                status_label.configure(text="❌ Funnel is INACTIVE", text_color="#9e9e9e")
                url_label.configure(text="", text_color="#4fc3f7")
            update_buttons()

        # ── UI Layout ───────────────────────────────────────────────────
        status_label = ctk.CTkLabel(
            dialog,
            text="Checking Tailscale status...",
            font=ctk.CTkFont(size=12),
            text_color="#aaa",
        )
        status_label.pack(pady=(20, 8))

        url_label = ctk.CTkLabel(
            dialog,
            text="",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#4fc3f7",
        )
        url_label.pack(pady=(0, 8))

        status_text = ctk.CTkLabel(
            dialog,
            text="⚠️ Storm must be running for funnel to work",
            font=ctk.CTkFont(size=10, slant="italic"),
            text_color="#999",
        )
        status_text.pack(pady=(0, 20))

        # ── Buttons ─────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=16, pady=(4, 8))

        def do_activate():
            """Start Tailscale funnel for Storm."""
            status_label.configure(text="Starting funnel...", text_color="#ff9800")
            url_label.configure(text="", text_color="#4fc3f7")
            btn_activate.configure(state="disabled")

            def _run():
                try:
                    result = subprocess.run(
                        ["wsl", "-d", WSL_DISTRO, "--", "bash", "-c",
                         "cd ~/.openclaw/workspace/projects/the-storm && source venv/bin/activate && tailscale funnel --bg --set-path / http://127.0.0.1:8001"],
                        capture_output=True, encoding="utf-8", text=True, timeout=15,
                    )
                    if result.returncode == 0:
                        import time
                        time.sleep(3)
                        url_result = subprocess.run(
                            ["wsl", "-d", WSL_DISTRO, "--", "tailscale", "funnel", "status"],
                            capture_output=True, encoding="utf-8", text=True, timeout=8,
                        )
                        if url_result.returncode == 0 and url_result.stdout.strip():
                            import re
                            url_match = re.search(r'https?://[^\s)]+', url_result.stdout)
                            if url_match:
                                funnel_url[0] = url_match.group(0)
                        else:
                            funnel_url[0] = ""

                        funnel_active[0] = True
                        self.root.after(0, _on_activate_success)
                    else:
                        error_msg = result.stderr.strip() or "Unknown error"
                        self.root.after(0, lambda e=error_msg: _on_error(e))
                except subprocess.TimeoutExpired:
                    self.root.after(0, lambda: _on_error("Timeout — tailscale command took too long"))
                except Exception as e:
                    self.root.after(0, lambda e=str(e): _on_error(str(e)))

            def _on_activate_success():
                status_label.configure(text="✅ Funnel is now ACTIVE", text_color="#4caf50")
                url_label.configure(text=funnel_url[0] or "No URL captured — check manually", text_color="#4fc3f7")
                update_buttons()

            def _on_error(msg):
                import tkinter.messagebox as tmsg
                self.root.after(0, lambda m=msg: tmsg.showerror("Funnel Error", f"Failed to start funnel:\n{m}"))
                status_label.configure(text="❌ Error starting funnel", text_color="#f44336")
                check_status()

            threading.Thread(target=_run, daemon=True).start()

        def do_deactivate():
            """Stop Tailscale funnel."""
            status_label.configure(text="Stopping funnel...", text_color="#ff9800")
            url_label.configure(text="", text_color="#4fc3f7")
            btn_deactivate.configure(state="disabled")

            def _run():
                try:
                    result = subprocess.run(
                        ["wsl", "-d", WSL_DISTRO, "--", "tailscale", "funnel", "reset"],
                        capture_output=True, encoding="utf-8", text=True, timeout=15,
                    )
                    if result.returncode == 0:
                        funnel_active[0] = False
                        funnel_url[0] = ""
                        self.root.after(0, _on_deactivate_success)
                    else:
                        error_msg = result.stderr.strip() or "Unknown error"
                        self.root.after(0, lambda e=error_msg: _on_error(e))
                except subprocess.TimeoutExpired:
                    self.root.after(0, lambda: _on_error("Timeout — tailscale command took too long"))
                except Exception as e:
                    self.root.after(0, lambda e=str(e): _on_error(str(e)))

            def _on_deactivate_success():
                status_label.configure(text="❌ Funnel is now INACTIVE", text_color="#9e9e9e")
                url_label.configure(text="", text_color="#4fc3f7")
                update_buttons()

            def _on_error(msg):
                import tkinter.messagebox as tmsg
                self.root.after(0, lambda m=msg: tmsg.showerror("Funnel Error", f"Failed to stop funnel:\n{m}"))
                status_label.configure(text="❌ Error stopping funnel", text_color="#f44336")
                check_status()

            threading.Thread(target=_run, daemon=True).start()

        btn_activate = ctk.CTkButton(
            btn_row,
            text="Activate Funnel",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=130, height=36,
            fg_color="#2d7d46", hover_color="#3a9e5a",
            text_color="white",
            corner_radius=4,
            command=do_activate,
        )
        btn_activate.pack(side="left", padx=(4, 2))

        btn_deactivate = ctk.CTkButton(
            btn_row,
            text="Deactivate Funnel",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=130, height=36,
            fg_color="#8b1e1e", hover_color="#a83232",
            text_color="white",
            corner_radius=4,
            command=do_deactivate,
        )
        btn_deactivate.pack(side="left", padx=(2, 2))

        ctk.CTkButton(
            btn_row,
            text="Close",
            font=ctk.CTkFont(size=12),
            width=130, height=36,
            fg_color="#555", hover_color="#777",
            text_color="white",
            corner_radius=4,
            command=dialog.destroy,
        ).pack(side="right", padx=(2, 4))

        # ── Initial status check (background thread) ────────────────────
        threading.Thread(target=check_status, daemon=True).start()

    def _show_shutdown_dialog(self):
        """Modal dialog to shutdown all services and close launcher."""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Shutdown All Services")
        dialog.geometry("320x400")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.transient(self.root)
        dialog.focus_set()

        # Center on root — use the known dialog geometry (320x400)
        x = self.root.winfo_x() + (self.root.winfo_width() - 320) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 400) // 2
        dialog.geometry(f"+{x}+{y}")

        # Warning text
        ctk.CTkLabel(
            dialog,
            text="⚠️ You are about to close the launcher.\nServices will continue running.",
            font=ctk.CTkFont(size=13),
            text_color="#ff6b6b",
            anchor="center",
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            dialog,
            text="Choose an option below.",
            font=ctk.CTkFont(size=11),
            text_color="#aaa",
        ).pack(pady=(0, 20))

        # Vertical button stack — one column, 4 rows
        def on_shutdown():
            dialog.destroy()
            self._shutdown_all_and_close(graceful=True)

        def on_force_kill():
            dialog.destroy()
            self._shutdown_all_and_close(graceful=False)

        def on_close_launcher():
            btn.configure(text="Closing Launcher", state="disabled")
            self.root.after(50, self._on_close)





        # Close Launcher — "leave my stuff running" (top, separate)
        btn = ctk.CTkButton(dialog, text="Close Launcher",
                      font=ctk.CTkFont(size=12),
                      fg_color="#555", hover_color="#777",
                      text_color="white", corner_radius=4,
                      width=160, height=36,
                      command=on_close_launcher)
        btn.pack(pady=(4, 8))

        # Divider — separates "close but continue" from "shut it down"
        ctk.CTkLabel(dialog, text="────────────",
                     font=ctk.CTkFont(size=12),
                     text_color="#666").pack(pady=(0, 8))

        # Shutdown buttons — the nuclear options below
        ctk.CTkButton(dialog, text="Force Kill & Close",
                      font=ctk.CTkFont(size=12),
                      fg_color="#8b1e1e", hover_color="#a83232",
                      text_color="white", corner_radius=4,
                      width=160, height=36,
                      command=on_force_kill).pack(pady=(0, 4))

        ctk.CTkButton(dialog, text="Shutdown All & Close",
                      font=ctk.CTkFont(size=12),
                      fg_color="#2d7d46", hover_color="#3a9e5a",
                      text_color="white", corner_radius=4,
                      width=160, height=36,
                      command=on_shutdown).pack(pady=4)

        ctk.CTkButton(dialog, text="Cancel",
                      font=ctk.CTkFont(size=12),
                      fg_color="#555", hover_color="#777",
                      text_color="white", corner_radius=4,
                      width=160, height=36,
                      command=dialog.destroy).pack(pady=(4, 20))

    def _shutdown_all_and_close(self, graceful=True):
        """Shutdown all running services and close launcher.
        
        In graceful mode: calls _stop_service() for each running service,
        which triggers the existing per-panel countdown UI ("⏳ Stopping... (5s)" → 0).
        A progress window shows overall status and auto-closes when done.
        
        In force-kill mode: immediately kills all tmux sessions, then closes.
        """
        services = list(SERVICE_ORDER)
        running_services = [k for k in services if self.service_states[k].running]

        if graceful:
            # --- Graceful shutdown ---
            # Start _stop_service countdown on each running panel (existing UI flow)
            for key in running_services:
                self._stop_service(key)

            # Progress window tracks completion
            prog = ctk.CTkToplevel(self.root)
            prog.title("Shutting Down")
            prog.geometry("380x250")
            prog.resizable(False, False)
            prog.grab_set()

            prog.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() - 380) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - 250) // 2
            prog.geometry(f"+{x}+{y}")

            title_label = ctk.CTkLabel(prog, text="Shutting down services...",
                                       font=ctk.CTkFont(size=14, weight="bold"))
            title_label.pack(pady=(20, 8))

            status_text = ctk.StringVar(value=f"Stopping {len(running_services)} service(s)...")
            status_label = ctk.CTkLabel(prog, textvariable=status_text,
                                        font=ctk.CTkFont(size=11),
                                        text_color="#aaa")
            status_label.pack(pady=(0, 12))

            progress = ctk.CTkProgressBar(prog, width=300)
            progress.pack(pady=(0, 16))
            progress.set(0)

            done_count = 0
            total = len(running_services)
            stopped_keys = set()

            def update_status(key, stopped):
                nonlocal done_count
                if stopped:
                    done_count += 1
                    stopped_keys.add(key)
                remaining = total - done_count
                if remaining > 0:
                    status_text.set(f"Stopping {remaining} service(s)...")
                else:
                    status_text.set("✅ All services shut down.")
                    progress.set(1.0)

            # Poll to check when all panels have stopped
            def _check_all_done():
                nonlocal done_count
                for key in running_services:
                    state = self.service_states[key]
                    if not state.running and key not in stopped_keys:
                        update_status(key, True)
                if all(not self.service_states[k].running for k in running_services):
                    prog.after(2000, lambda: (prog.destroy(), self.root.destroy()))
                else:
                    prog.after(500, _check_all_done)

            prog.after(500, _check_all_done)
            prog.protocol("WM_DELETE_WINDOW", lambda: None)
        else:
            # --- Force kill all immediately ---
            for key in running_services:
                svc = SERVICES.get(key, {})
                tmux_name = svc.get("tmux_session", "")
                try:
                    subprocess.run(
                        ["wsl", "-d", WSL_DISTRO, "--", "tmux", "kill-session", "-t", tmux_name],
                        capture_output=True, encoding="utf-8", text=True, timeout=5,
                    )
                except Exception as e:
                    logger.error("[SHUTDOWN_FORCE] Kill failed for %s: %s", key, e)

            # Update all UI to stopped state
            for key in running_services:
                self.root.after(0, self._update_service_ui, key, False)

            prog = ctk.CTkToplevel(self.root)
            prog.title("Shutting Down")
            prog.geometry("380x200")
            prog.resizable(False, False)
            prog.grab_set()
            prog.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() - 380) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - 200) // 2
            prog.geometry(f"+{x}+{y}")

            ctk.CTkLabel(prog, text="☠️ Force-killed all services.",
                        font=ctk.CTkFont(size=14)).pack(pady=(30, 8))
            status_text = ctk.StringVar(value="Closing...")
            ctk.CTkLabel(prog, textvariable=status_text,
                        font=ctk.CTkFont(size=11), text_color="#aaa").pack()

            prog.after(2000, lambda: (prog.destroy(), self.root.destroy()))

    def _rebuild_all_service_blocks(self):
        """Rebuild all service blocks after reorder or major change."""
        # Clear expanded zone grid
        for w in self._expanded_zone.winfo_children():
            w.destroy()
        # Clear collapsed zone grid
        for w in self._collapsed_zone.winfo_children():
            w.destroy()
        # Rebuild
        for key in SERVICE_ORDER:
            if key in SERVICES:
                self._build_service_block(key)
        self._recalc_layout()

    def _show_service_form_dialog(self, existing_key=None):
        """Unified add/edit service form dialog.
        
        Args:
            existing_key: If None → add mode. If str → edit mode for that key.
        """
        mode = "edit" if existing_key else "add"
        is_edit = existing_key is not None

        self._form_dialog = ctk.CTkToplevel(self.root)
        title = f"Edit Service: {existing_key}" if is_edit else "Add New Service"
        self._form_dialog.title(title)
        self._form_dialog.geometry("520x480")
        self._form_dialog.resizable(False, False)
        self._form_dialog.grab_set()
        self._form_dialog.transient(self.root)

        x = self.root.winfo_x() + (self.root.winfo_width() - 520) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 480) // 2
        self._form_dialog.geometry(f"+{x}+{y}")

        def on_close():
            if hasattr(self, "_form_dialog") and self._form_dialog.winfo_exists():
                self._form_dialog.destroy()
        self._form_dialog.protocol("WM_DELETE_WINDOW", on_close)

        scroll = ctk.CTkScrollableFrame(self._form_dialog, width=490, height=380)
        scroll.pack(pady=4, padx=16, expand=True, fill="both")

        # ── Field definitions: (attr_prefix, label_text, placeholder, is_required, entry_type) ──
        fields = [
            ("key",   "Key *",      "archivist",              True,  "entry"),
            ("name",  "Name * (Max 24 characters)", "Archivist (Qwen3.5-9B)", True,  "entry"),
            ("port",  "Port * (0=process-only)",  "8081",           True,  "entry"),
            ("tmux",  "tmux session","archivist",              False, "entry"),
            ("log",   "Log file",    "/mnt/c/Users/User/ai-lab-launcher/logs/archivist.log",   False, "entry"),
            ("cmd",   "Command *",   "",                       True,  "textbox"),
        ]

        # Create all field widgets inline with error labels
        entry_refs = {}    # prefix → widget
        err_refs = {}      # prefix → error label
        name_count_label = None  # Live character counter for Name field
        MAX_NAME_LEN = 24  # Max characters allowed for service name

        for prefix, label, placeholder, required, etype in fields:
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=(2, 2), padx=4)
            
            req_mark = " *" if required else ""
            ctk.CTkLabel(row, text=label, width=100, anchor="w",
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=(4, 8))

            if etype == "textbox":
                widget = ctk.CTkTextbox(scroll, font=ctk.CTkFont(family="Consolas", size=10),
                                        height=80, width=460)
            else:
                if is_edit:
                    widget = ctk.CTkEntry(scroll, font=ctk.CTkFont(size=11), height=28)
                else:
                    widget = ctk.CTkEntry(scroll, font=ctk.CTkFont(size=11), height=28,
                                          placeholder_text=placeholder)

            widget.bind("<Button-3>", lambda e, w=widget: self._show_ctx(e))
            widget.pack(fill="x" if etype == "entry" else "both", expand=(etype == "textbox"),
                        padx=4, pady=(0, 2))

            err = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=9), text_color="#ff6b6b")
            err.pack(fill="x", padx=4, pady=(0, 2))

            entry_refs[prefix] = widget
            err_refs[prefix] = err

        # ── Name field: cap at 30 chars with live feedback ─────────
        if "name" in entry_refs:
            name_count_label = ctk.CTkLabel(
                scroll, text=f"{len(entry_refs['name'].get().strip())}/{MAX_NAME_LEN}",
                font=ctk.CTkFont(size=9), text_color="#888"
            )
            name_count_label.pack(fill="x", padx=4, pady=(0, 2))

            def _on_name_change(*_):
                val = entry_refs["name"].get()
                if len(val) > MAX_NAME_LEN:
                    entry_refs["name"].delete(MAX_NAME_LEN, "end")
                    val = val[:MAX_NAME_LEN]
                remaining = MAX_NAME_LEN - len(val)
                color = "#ff6b6b" if remaining <= 3 else "#888"
                name_count_label.configure(text=f"{len(val)}/{MAX_NAME_LEN} ({remaining} left)", text_color=color)

            entry_refs["name"].bind("<KeyRelease>", _on_name_change)
            entry_refs["name"].bind("<ButtonRelease>", _on_name_change)

        # Pre-fill values in edit mode
        if is_edit:
            svc = SERVICES[existing_key]
            # Insert text BEFORE setting readonly (CTkEntry needs editable to accept insert)
            entry_refs["key"].delete(0, "end")
            entry_refs["key"].insert(0, existing_key)
            entry_refs["key"].configure(state="readonly")
            name_val = svc.get("name", "")[:MAX_NAME_LEN]
            entry_refs["name"].delete(0, "end")
            entry_refs["name"].insert(0, name_val)
            # Sync counter after pre-fill
            if name_count_label:
                remaining = MAX_NAME_LEN - len(name_val)
                color = "#ff6b6b" if remaining <= 3 else "#888"
                name_count_label.configure(text=f"{len(name_val)}/{MAX_NAME_LEN} ({remaining} left)", text_color=color)
            entry_refs["port"].delete(0, "end")
            entry_refs["port"].insert(0, str(svc.get("port", "")))
            entry_refs["tmux"].delete(0, "end")
            entry_refs["tmux"].insert(0, svc.get("tmux_session", ""))
            entry_refs["log"].delete(0, "end")
            entry_refs["log"].insert(0, svc.get("log_file", ""))
            entry_refs["cmd"].delete("1.0", "end")
            entry_refs["cmd"].insert("1.0", svc.get("command", ""))

        # Auto-fill tmux & log when key changes (add mode only)
        if not is_edit:
            def _on_key_change(*_):
                k = entry_refs["key"].get().strip().lower().replace(" ", "_")
                if k:
                    entry_refs["tmux"].delete(0, "end")
                    entry_refs["tmux"].insert(0, f"{k}_server")
                    entry_refs["log"].delete(0, "end")
                    entry_refs["log"].insert(0, f"/mnt/c/Users/User/ai-lab-launcher/logs/{k}.log")
            entry_refs["key"].bind("<KeyRelease>", _on_key_change)

        # ── Buttons ──
        btn_row = ctk.CTkFrame(self._form_dialog, fg_color="transparent")
        btn_row.pack(fill="x", pady=(4, 8), padx=16)

        def on_ok():
            key = entry_refs["key"].get().strip()
            name = entry_refs["name"].get().strip()
            port_s = entry_refs["port"].get().strip()
            tmux = entry_refs["tmux"].get().strip()
            log_f = entry_refs["log"].get().strip()
            cmd = entry_refs["cmd"].get("1.0", "end-1c").strip()

            # Clear all inline errors
            for el in err_refs.values():
                el.configure(text="")

            errors = []
            if not key:
                errors.append("Key is required")
            elif not is_edit and key in SERVICES:
                errors.append(f'Key "{key}" already exists')
            if not name:
                errors.append("Name is required")
            elif len(name) > MAX_NAME_LEN:
                errors.append(f"Name must be {MAX_NAME_LEN} characters or fewer")
            if not port_s:
                errors.append("Port is required")
            else:
                try:
                    int(port_s)
                except ValueError:
                    errors.append("Port must be a number")
            if not cmd:
                errors.append("Command is required")

            if errors:
                for err_msg in errors:
                    if err_msg.startswith("Key"):
                        err_refs["key"].configure(text=err_msg)
                    elif err_msg.startswith("Name"):
                        err_refs["name"].configure(text=err_msg)
                    elif err_msg.startswith("Port"):
                        err_refs["port"].configure(text=err_msg)
                    elif err_msg.startswith("Command"):
                        err_refs["cmd"].configure(text=err_msg)
                return

            if is_edit:
                # Update existing service
                SERVICES[key] = {
                    "name": name,
                    "port": int(port_s),
                    "tmux_session": tmux or svc.get("tmux_session", f"{key}_server"),
                    "log_file": log_f or svc.get("log_file", f"/mnt/c/Users/User/ai-lab-launcher/logs/{key}.log"),
                    "command": cmd,
                }
            else:
                # Add new service
                SERVICES[key] = {
                    "name": name,
                    "port": int(port_s),
                    "tmux_session": tmux or f"{key}_server",
                    "log_file": log_f or f"/mnt/c/Users/User/ai-lab-launcher/logs/{key}.log",
                    "command": cmd,
                }
                SERVICE_ORDER.append(key)
                self.service_states[key] = ServiceState()
                self._service_ui_refs[key] = {}

            # Destroy old widgets for this key before rebuilding (edit mode fix)
            if is_edit and key in self._service_ui_refs:
                for w in self._service_ui_refs[key].values():
                    try:
                        w.destroy()
                    except Exception:
                        pass
            self._service_ui_refs[key] = {}

            # Rebuild UI panel and refresh (both add and edit)
            if not is_edit or key in SERVICES:
                self._build_service_block(key)
                self._recalc_layout()

            _save_services()
            self._form_dialog.destroy()

        btn_text = "Save" if is_edit else "Add"
        ctk.CTkButton(btn_row, text=btn_text, font=ctk.CTkFont(size=12, weight="bold"),
                      width=100, height=32, fg_color="#2d7d46", hover_color="#3a9e5a",
                      command=on_ok).pack(side="left", padx=(4, 2))

        ctk.CTkButton(btn_row, text="Cancel", font=ctk.CTkFont(size=12),
                      width=100, height=32, fg_color="#333", hover_color="#555",
                      command=lambda: self._form_dialog.destroy()).pack(side="right", padx=(2, 4))

        self._form_dialog.wait_window()

    def _show_add_service_dialog(self):
        """Show add-service dialog (wrapper)."""
        self._show_service_form_dialog(existing_key=None)

    def _show_edit_service_dialog(self, key):
        """Show edit-service dialog (wrapper)."""
        self._show_service_form_dialog(existing_key=key)


    def _kill_service_process(self, key):
        """Force-kill a service process — immediate, no countdown."""
        if key not in SERVICES or key not in self.service_states:
            return
        svc = SERVICES[key]
        state = self.service_states[key]
        refs = self._service_ui_refs.get(key)

        # Confirmation dialog
        self._kill_dialog = ctk.CTkToplevel(self.root)
        self._kill_dialog.title("Kill Service")
        self._kill_dialog.geometry("400x200")
        self._kill_dialog.resizable(False, False)
        self._kill_dialog.grab_set()
        self._kill_dialog.transient(self.root)

        x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 200) // 2
        self._kill_dialog.geometry(f"+{x}+{y}")

        def on_close():
            if hasattr(self, "_kill_dialog") and self._kill_dialog.winfo_exists():
                self._kill_dialog.destroy()
        self._kill_dialog.protocol("WM_DELETE_WINDOW", on_close)

        ctk.CTkLabel(
            self._kill_dialog,
            text=f"Force-kill \"{svc.get('name', key)}\"?\n\nThis will immediately terminate the process\nwith no graceful shutdown or cleanup.",
            font=ctk.CTkFont(size=12),
            wraplength=350,
            text_color="#ff6b6b",
        ).pack(pady=(20, 10))

        ctk.CTkLabel(
            self._kill_dialog,
            text="This cannot be undone.",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#999",
        ).pack(pady=(0, 20))

        def do_kill():
            # Stop background threads
            state._log_refresh_stop.set()
            state._stop_event.set()
            if state.poll_thread and state.poll_thread.is_alive():
                state.poll_thread.join(timeout=1)
            if state.log_refresh_thread and state.log_refresh_thread.is_alive():
                state.log_refresh_thread.join(timeout=1)

            # Force-kill tmux session (no countdown)
            try:
                subprocess.run(
                    ["wsl", "-d", WSL_DISTRO, "--", "tmux", "kill-session", "-t", svc["tmux_session"]],
                    capture_output=True, encoding="utf-8", text=True, timeout=5,
                )
            except Exception:
                pass

            # Update UI to stopped state immediately
            if refs:
                self.root.after(0, lambda k=key: self._update_service_ui(k, False))

            # Close dialog
            if hasattr(self, "_kill_dialog") and self._kill_dialog.winfo_exists():
                self._kill_dialog.destroy()

        btn_row = ctk.CTkFrame(self._kill_dialog, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=16, pady=(4, 8))
        ctk.CTkButton(btn_row, text="Kill", font=ctk.CTkFont(size=12, weight="bold"),
                      width=100, height=32, fg_color="#cc3333", hover_color="#e04040",
                      text_color="white", command=do_kill).pack(side="left", padx=(4, 2))
        ctk.CTkButton(btn_row, text="Cancel", font=ctk.CTkFont(size=12),
                      width=100, height=32, fg_color="#333", hover_color="#555",
                      command=lambda: self._kill_dialog.destroy()).pack(side="right", padx=(2, 4))

        self._kill_dialog.wait_window()

    def _confirm_delete_service(self, key):
        """Confirm deletion and remove service from UI + JSON."""
        if key not in SERVICES:
            return
        
        svc = SERVICES[key]
        
        # Confirmation dialog
        self._delete_dialog = ctk.CTkToplevel(self.root)
        self._delete_dialog.title("Delete Service")
        self._delete_dialog.geometry("400x250")
        self._delete_dialog.resizable(False, False)
        self._delete_dialog.grab_set()
        self._delete_dialog.transient(self.root)
        
        x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 250) // 2
        self._delete_dialog.geometry(f"+{x}+{y}")
        
        def on_close():
            if hasattr(self, "_delete_dialog") and self._delete_dialog.winfo_exists():
                self._delete_dialog.destroy()
        self._delete_dialog.protocol("WM_DELETE_WINDOW", on_close)
        
        ctk.CTkLabel(
            self._delete_dialog,
            text=f"Are you sure you want to delete\n\"{svc.get('name', key)}\"?\nThis action cannot be undone.",
            font=ctk.CTkFont(size=12),
            wraplength=350
        ).pack(pady=(20, 10))
        
        ctk.CTkLabel(
            self._delete_dialog,
            text="Service must be stopped before deletion.",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#999"
        ).pack(pady=(0, 20))
        
        def on_delete():
            # Stop service if running
            state = self.service_states.get(key)
            if state and (state.running or state._starting):
                self.root.after(0, lambda k=key: self._stop_service(k))
                # Wait for stop to complete before removing
                self.root.after(3000, _do_delete_service)
            else:
                _do_delete_service()
        
        def _do_delete_service():
            # Capture refs for the deleted service before we remove it
            deleted_refs = self._service_ui_refs.get(key, {})

            # Remove from data structures
            SERVICES.pop(key, None)
            if key in SERVICE_ORDER:
                SERVICE_ORDER.remove(key)
            self.service_states.pop(key, None)
            self._service_ui_refs.pop(key, None)

            # Save to JSON
            _save_services()

            # Destroy the deleted service's UI elements
            if deleted_refs:
                for w in ("strip_frame", "panel_frame"):
                    if w in deleted_refs:
                        try:
                            deleted_refs[w].destroy()
                        except Exception:
                            pass

            # Rebuild all service blocks from current state
            for svc_key in SERVICE_ORDER:
                if svc_key in SERVICES:
                    self._build_service_block(svc_key)
            self._recalc_layout()

            # Close dialog
            if hasattr(self, "_delete_dialog") and self._delete_dialog.winfo_exists():
                self._delete_dialog.destroy()
        
        btn_row = ctk.CTkFrame(self._delete_dialog, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=16, pady=(4, 8))
        ctk.CTkButton(btn_row, text="Delete", font=ctk.CTkFont(size=12, weight="bold"),
                      width=100, height=32, fg_color="#a83232", hover_color="#c44040",
                      command=on_delete).pack(side="left", padx=(4, 2))
        ctk.CTkButton(btn_row, text="Cancel", font=ctk.CTkFont(size=12),
                      width=100, height=32, fg_color="#333", hover_color="#555",
                      command=lambda: self._delete_dialog.destroy()).pack(side="right", padx=(2, 4))
        
        self._delete_dialog.wait_window()

    # ── Toggle / Start / Stop ───────────────────────────────────

    def _toggle_service(self, key):
        """Start or stop a service based on its current state."""
        state = self.service_states[key]
        refs = self._service_ui_refs.get(key)
        if not refs:
            return

        if state.running or state._starting:
            # Service is running → stop it
            self._stop_service(key)
        else:
            # Service is stopped → start it, and expand panel if collapsed
            if state._collapsed:
                state._collapsed = False
                refs["panel_frame"].grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
                refs["collapse_btn"].configure(text="▼")
                if "collapse_btn_panel" in refs:
                    refs["collapse_btn_panel"].configure(text="▲")
                self._recalc_layout()
            self._start_service(key)

    def _toggle_collapse(self, key):
        """Toggle collapsed/expanded state of a service block."""
        state = self.service_states[key]
        refs = self._service_ui_refs[key]
        if not refs:
            return

        if state._collapsed:
            # Collapsed → expand
            state._collapsed = False
            refs["panel_frame"].grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
            refs["collapse_btn"].configure(text="▼")
            if "collapse_btn_panel" in refs:
                refs["collapse_btn_panel"].configure(text="▲")
            # Show Edit/Delete when expanded
            refs["edit_btn"].pack(side="left", padx=(6, 3))
            refs["delete_btn"].pack(side="left", padx=(3, 3))
            refs["kill_btn"].pack(side="left", padx=(3, 0))
        else:
            # Expanded → collapse
            state._collapsed = True
            refs["panel_frame"].grid_remove()
            refs["collapse_btn"].configure(text="▶")
            if "collapse_btn_panel" in refs:
                refs["collapse_btn_panel"].configure(text="▼")
            # Hide Edit/Delete when collapsed
            refs["edit_btn"].pack_forget()
            refs["delete_btn"].pack_forget()
            refs["kill_btn"].pack_forget()

        self._recalc_layout()

    def _start_service(self, key):
        """Start a service in a tmux session."""
        state = self.service_states[key]
        svc = SERVICES[key]
        # Check refs exist first
        refs = self._service_ui_refs.get(key)
        if not refs:
            return False
        
        # Check if already running (idempotent guard)
        result = subprocess.run(
            ["wsl", "-d", WSL_DISTRO, "--", "tmux", "has-session", "-t", svc["tmux_session"]],
            capture_output=True,
            encoding="utf-8",
            text=True,
        )

        if result.returncode == 0:
            # Already running — show Starting... then restart threads
            self.root.after(0, self._update_starting_ui, key)
            state._starting = True
            state._stop_event.clear()
            state.poll_thread = threading.Thread(target=self._health_poll, args=(key,), daemon=True)
            state.poll_thread.start()

            state._log_refresh_stop.clear()
            state.log_refresh_thread = threading.Thread(target=self._log_refresh_loop, args=(key,), daemon=True)
            state.log_refresh_thread.start()
            return True

        # Show "Starting..." immediately so user gets visual feedback
        self.root.after(0, self._update_starting_ui, key)

        # Launch in tmux — bash -c 'exec cmd' so stdout goes directly to PTY
        # (no send-keys race, no intermediary shell, output visible immediately).
        # Explicit dimensions avoid 80-col wrap; remain-on-exit preserves dead pane.
        launch_cmd = (
            f"PYTHONUNBUFFERED=1 {svc['command']} 2>&1 | tee {svc['log_file']}; "
            f"tail -f /dev/null & wait"
        )
        try:
            subprocess.run(
                ["wsl", "-d", WSL_DISTRO, "--",
                 "tmux", "new-session", "-d",
                 "-s", svc["tmux_session"],
                 "-x", "220", "-y", "60",
                 f"bash -c 'export PYTHONUNBUFFERED=1; {svc['command']} 2>&1 | tee {svc['log_file']}; tail -f /dev/null & wait'"],
                check=True, encoding="utf-8", capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            if refs:
                self.root.after(0, lambda k=key, r=refs: r["status_label"].configure(text="❌ Failed to start", text_color="#ff4444"))
            logger.error("[START] CalledProcessError for %s: %s", key, e)
            return False
        except FileNotFoundError:
            if refs:
                self.root.after(0, lambda k=key, r=refs: r["status_label"].configure(text="❌ WSL not available", text_color="#ff4444"))
            logger.error("[START] FileNotFoundError for %s — WSL may not be installed", key)
            return False
        except OSError as e:
            if refs:
                self.root.after(0, lambda k=key, r=refs: r["status_label"].configure(text="❌ OS Error", text_color="#ff4444"))
            logger.error("[START] OSError for %s: %s", key, e)
            return False

        # Mark starting BEFORE health poll thread so it doesn't show "Stopped"
        state._starting = True
        state._stop_event.clear()
        state.poll_thread = threading.Thread(target=self._health_poll, args=(key,), daemon=True)
        state.poll_thread.start()

        state._log_refresh_stop.clear()
        state.log_refresh_thread = threading.Thread(target=self._log_refresh_loop, args=(key,), daemon=True)
        state.log_refresh_thread.start()
        
        return True

    def _stop_service(self, key):
        """Gracefully stop a service with countdown."""
        state = self.service_states[key]
        svc = SERVICES[key]
        refs = self._service_ui_refs.get(key)

        if not refs:
            return

        # Stop background threads
        state._log_refresh_stop.set()
        state._stop_event.set()
        if state.poll_thread and state.poll_thread.is_alive():
            state.poll_thread.join(timeout=2)
        if state.log_refresh_thread and state.log_refresh_thread.is_alive():
            state.log_refresh_thread.join(timeout=2)

        # Send Ctrl+C to tmux session
        try:
            subprocess.run(
                ["wsl", "-d", WSL_DISTRO, "--", "tmux", "send-keys", "-t", svc["tmux_session"], "C-c"],
                capture_output=True, encoding="utf-8", text=True, timeout=3,
            )
        except Exception:
            pass

        # Non-blocking countdown via root.after()
        self._countdown(key, 5)

    def _countdown(self, key, remaining):
        """Run shutdown countdown on the UI thread (non-blocking)."""
        svc = SERVICES[key]
        refs = self._service_ui_refs.get(key)

        if not refs:
            return

        if remaining > 0:
            msg = f"⏳ Stopping... ({remaining}s)"
            self.root.after(0, lambda k=key, r=remaining: self._update_shutdown_ui(k, r))
            self.root.after(1000, self._countdown, key, remaining - 1)
        else:
            # Force kill if still running
            try:
                result = subprocess.run(
                    ["wsl", "-d", WSL_DISTRO, "--", "tmux", "has-session", "-t", svc["tmux_session"]],
                    capture_output=True, encoding="utf-8", text=True,
                )
                if result.returncode == 0:
                    subprocess.run(
                        ["wsl", "-d", WSL_DISTRO, "--", "tmux", "kill-session", "-t", svc["tmux_session"]],
                        capture_output=True, encoding="utf-8", text=True, timeout=5,
                    )
            except Exception as e:
                logger.error("[COUNTDOWN] Force-kill failed for %s: %s", key, e)

            # Verify kill actually worked before telling user "Stopped"
            try:
                verify = subprocess.run(
                    ["wsl", "-d", WSL_DISTRO, "--", "tmux", "has-session", "-t", svc["tmux_session"]],
                    capture_output=True, encoding="utf-8", text=True, timeout=5,
                )
                if verify.returncode == 0:
                    # Still running — force-kill didn't work
                    self.root.after(0, lambda k=key: (
                        self._service_ui_refs.get(k, {}).get("status_label").configure(
                            text="❌ Force-kill failed", text_color="#ff4444"
                        ) if k in self._service_ui_refs else None
                    ))
                else:
                    # Session gone — safe to mark stopped
                    self.root.after(0, self._update_service_ui, key, False)
            except Exception as e:
                logger.error("[COUNTDOWN] Verification failed for %s: %s", key, e)
                self.root.after(0, self._update_service_ui, key, False)

    # ── Shutdown ────────────────────────────────────────────────

    def _on_close(self):
        """Handle window close — clean up UI threads only, leave services running."""
        import traceback
        logger.info("=== _on_close ENTERED ===")

        try:
            # Count running services BEFORE cleanup for debugging
            running_count_before = sum(1 for k in SERVICE_ORDER if self.service_states[k].running)
            logger.info("Services running before cleanup: %d", running_count_before)

            for key in SERVICE_ORDER:
                state = self.service_states[key]
                state._stop_event.set()
                if state.poll_thread and state.poll_thread.is_alive():
                    state.poll_thread.join(timeout=2)
                if state.log_refresh_thread and state.log_refresh_thread.is_alive():
                    state.log_refresh_thread.join(timeout=2)

            # Stop GPU monitoring
            self._gpu_stop.set()

            # Count running services after cleanup
            running_count_after = sum(1 for k in SERVICE_ORDER if self.service_states[k].running)
            logger.info("Services running after cleanup: %d", running_count_after)

            # Quiet close — no dialog, just destroy immediately
            logger.info("Destroying root...")
            self.root.destroy()
            logger.info("Root destroyed.")

        except Exception as e:
            logger.critical("CRASHED: %s", e)
            logger.critical("%s", traceback.format_exc(), exc_info=True)
            raise  # Re-raise so Python prints to stderr too



if __name__ == "__main__":
    app = LauncherApp()
    app.root.mainloop()
