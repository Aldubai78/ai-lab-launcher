# AI Lab Launcher

Desktop dashboard for managing local AI inference services on Windows via WSL2.

## What It Is

A single-file Python GUI that lets you start, stop, and monitor multiple backend services running inside tmux sessions on WSL2 Ubuntu. Think of it as a remote control for your local AI lab.

Services managed via JSON config — add, edit, reorder, favourite, or delete without touching code.

## Services

| Example Service | Port | Description |
|---------|------|-------------|
| Main LLM | 8080 | llama.cpp server for your primary model |
| Archivist | 8081 | Smaller model for background memory work |
| Embedding Server | 8082 | Local embedding model (e.g. nomic-embed) |
| Vision Server | 8083 | llama.cpp multimodal (mmproj) server |

The example `services.json` ships with a few of these plus placeholders for
a Whisper PTT server, a Python web service, and a Docker Compose service.
Edit or add your own via the **+ New Service** dialog — the launcher never
assumes which services exist.

## Requirements

- Windows 10/11 with WSL2 (Ubuntu 22.04/24.04)
- Python 3.10+ on Windows
- tmux installed inside WSL2
- CustomTkinter, psutil (`pip install -r requirements.txt`)
- Whatever your services need (GPU VRAM, Docker, etc.)

## Quick Start

1. **First run:** copy the example config and edit it to your lab:

   ```bat
   copy services.json.example services.json
   ```

   Open `services.json` — set your model paths, ports, and tmux session names.
   Everything is editable live from the GUI too.

2. **Launch:**

   ```bat
   launcher.bat
   ```

   Or: `python launcher.py`

The app auto-detects which services are already running in tmux and shows their status on startup.

## Features

- **One-click service management** — Start, stop, force-kill with colour-coded status indicators
- **Live terminal logs** — Real-time capture from tmux `capture-pane`, character-wrap matching actual terminal behaviour, diff-based skip to eliminate flicker
- **Floating log windows** — Detach any service's log panel into its own window for multi-monitor setups
- **GPU monitoring strip** — Dual GPU polling every 0.5s (fan%, temp, power draw, memory)
- **Favourites quick-launch** — Checkbox modal to start a selected subset of services at once
- **Layout toggle** — Switch between vertical stack and horizontal spread
- **Reorderable service list** — Up/down buttons in reorder dialog, persisted to JSON
- **Graceful shutdown** — Ctrl+C triggers 5-second countdown with per-service progress; force-kill if processes survive
- **Tailscale funnel** — Activate/deactivate public URLs for services, displayed URL on open
- **Right-click paste** — Context menus on all input fields
- **JSON persistence** — All config changes (services, order, layout mode, favourites) saved to `services.json`
- **Thread-safe UI** — All background thread updates routed through `root.after()`

## Architecture

```
Windows GUI (launcher.py, CustomTkinter)
    │
    ├── data_layer.py ──→ JSON persistence, service CRUD, state reconstruction
    │
    ├── tmux sessions via wsl.exe ──→ WSL2 Ubuntu 24.04
    │                                   └── llama.cpp servers
    │                                   └── Storm + Doug's Bridge
    │
    └── services.json ──→ persistent config (JSON)
```

Each service runs inside a named tmux session (`tmux_session` field). The launcher polls health via TCP connect (or tmux session check for process-only services), captures logs via `capture-pane`, and updates UI through thread-safe callbacks.

## Project Structure

The launcher has two main components:

| File | Purpose |
|------|---------|
| `launcher.py` | GUI application (~2500 lines) — UI, tmux management, GPU monitoring |
| `data_layer.py` | Pure Python data layer (~240 lines) — JSON persistence, service CRUD, no UI deps |

The data layer can be imported and tested independently of the GUI.

## Known Limitations

- Ad-hoc debug logging (scattered file writes instead of proper `logging` module)
- Windows-only (WSL2 dependency)
- No packaging — requires Python + dependencies installed manually

## Files

```
launcher.py              Main application (~105KB)
services.json.example    Example config (copy to services.json on first run)
services.json            YOUR config (gitignored — never committed)
data_layer.py            Data layer: load/save/build/crud operations
tests/test_data_layer.py 24 tests covering JSON persistence, CRUD, edge cases
requirements.txt         Python dependencies
launcher.bat             Quick-launch script
REFACTOR-PLAN.md         Refactor history + post-mortem + lessons learned
```

## Testing

Run the automated test suite:

```bash
pytest tests/test_data_layer.py -v
```

Covers: JSON load/save round-trips, service CRUD, order preservation, layout cycling, edge cases. Runs in ~0.1s without a display server.

## Version History

- **v1.4** (2026-11-18) — New-service dialog suggests `<project>/logs/<key>.log` as the log path default
- **v1.3** (2026-08-18) — Data layer extraction to `data_layer.py`, 24 automated tests for JSON persistence and CRUD
- **v1.0** (2026-08-10) — Initial release: full service management, JSON persistence, GPU monitoring, log panels, shutdown countdown, favourites, layout toggle, reorder dialog, Tailscale funnel
- **v1.1** (2026-08-10) — Error handling hardening: try/except on health poll, log refresh, countdown verification, service start exception handling
- **v1.2** (2026-08-10) — Log panel polish: character-wrap, diff-based skip, capture-pane capped at 200 lines, flicker elimination
