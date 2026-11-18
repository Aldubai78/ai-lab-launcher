"""
Data layer for AI Lab Launcher — pure Python, no UI dependencies.

Handles JSON persistence (services.json), service CRUD operations,
and state reconstruction. This module can be imported and tested
independently of the GUI.

Usage:
    >>> from data_layer import load_services, build_services, save_services
    >>> data = load_services()
    >>> build_services(data)
    >>> save_services()
"""

import json
import os as _os
import sys

# Path to services.json — can be overridden for testing
_SERVICES_FILE = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "services.json"
)

# Default service definitions (used when services.json is missing/corrupt)
# Note: llama.cpp path is injected at runtime via launcher.py's LLAMA_SERVER_PATH
# or can be overridden by setting data_layer.LLAMA_SERVER_PATH before import.
_LLAMA_SERVER_PATH = getattr(sys.modules[__name__], "LLAMA_SERVER_PATH", "/usr/local/bin/llama-server")

_DEFAULTS = {
    "storm": {
        "name": "Storm Server",
        "port": 8001,
        "tmux_session": "storm_server",
        "log_file": "~/logs/storm.log",
        "command": "bash -c 'cd /home/allen/.openclaw/workspace/projects/the-storm && source venv/bin/activate && python3 web_server.py'",
    },
    "vision": {
        "name": "Vision Server",
        "port": 8083,
        "tmux_session": "vision_server",
        "log_file": "~/logs/vision.log",
        "command": f"{_LLAMA_SERVER_PATH} -m ~/llama.cpp/models/Qwen_Qwen3-VL-8B-Instruct-Q6_K_L.gguf --mmproj ~/llama.cpp/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf --port 8083 --ctx-size 8192 -ngl 99 --flash-attn on",
    },
    "archivist": {
        "name": "Archivist (Qwen3.5-9B)",
        "port": 8081,
        "tmux_session": "archivist",
        "log_file": "~/logs/archivist.log",
        "command": f"CUDA_VISIBLE_DEVICES=0 {_LLAMA_SERVER_PATH} -m ~/llama.cpp/models/Qwen3.5-9B-Q6_K.gguf --ctx-size 131072 -ngl 99 --jinja --flash-attn on --reasoning off --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 --presence-penalty 1.5 --repeat-penalty 1.0 -b 2048 -ub 1024 --host 127.0.0.1 --api-key-file ~/.config/llama/api.key --port 8081",
    },
    "embedding": {
        "name": "Embedding Server",
        "port": 8082,
        "tmux_session": "embedding_server",
        "log_file": "~/logs/embedding.log",
        "command": f"CUDA_VISIBLE_DEVICES=0 {_LLAMA_SERVER_PATH} -m /home/allen/llama.cpp/models/nomic-embed-text-v1.5.Q8_0.gguf --alias nomic-embed --embedding --host 127.0.0.1 --api-key-file ~/.config/llama/api.key --port 8082 --ctx-size 32768 -b 8192 -ub 8192 --parallel 4 -ngl 99 --override-kv nomic-bert.context_length=int:8192 --rope-scaling yarn --rope-freq-scale 0.75",
    },
}

# Runtime state (populated by build_services)
SERVICES = {}           # key -> service dict
SERVICE_ORDER = []      # ordered list of service keys
_standard_services = [] # favourites (subset of SERVICE_ORDER)
_LAYOUT_MODES = ["2cols", "2rows"]  # layout mode options


def load_services(services_file=None):
    """Load services from JSON, falling back to defaults if file missing/corrupt.

    Args:
        services_file: Path to services.json. Uses default if None.

    Returns:
        dict: Merged service data (defaults + any keys from JSON).
    """
    path = services_file or _SERVICES_FILE
    try:
        if _os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
            # Validate structure — merge any missing keys from defaults
            for k in _DEFAULTS:
                if k not in data:
                    data[k] = _DEFAULTS[k]
            return data
    except (json.JSONDecodeError, IOError):
        pass  # corrupt file → fall back to defaults
    return dict(_DEFAULTS)


def save_services(services_file=None):
    """Persist current state to JSON.

    Args:
        services_file: Path to services.json. Uses default if None.
    """
    path = services_file or _SERVICES_FILE
    payload = {
        "_order": SERVICE_ORDER,
        "_standard": list(_standard_services),
        **SERVICES,
    }
    _write_services_json(payload, path)


def write_services_json(payload, services_file=None):
    """Write payload dict to services.json. Low-level — no validation.

    Args:
        payload: Dict to serialize.
        services_file: Path to services.json. Uses default if None.
    """
    path = services_file or _SERVICES_FILE
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def build_services(raw_data):
    """Build SERVICES dict, SERVICE_ORDER list, and _standard_services from raw JSON data.

    This is the reconstruction step that turns parsed JSON into runtime state.

    Args:
        raw_data: Dict loaded from services.json (via load_services).
    """
    global SERVICES, SERVICE_ORDER, _standard_services

    # Extract special keys first
    standard_keys = []
    if "_standard" in raw_data and isinstance(raw_data["_standard"], list):
        standard_keys = raw_data["_standard"]

    # Extract order array if present (stored as "_order" key in JSON)
    order_keys = []
    for k, v in raw_data.items():
        if k == "_order":
            order_keys = v
            break
    else:
        # No _order key — use dict insertion order
        order_keys = list(raw_data.keys())

    SERVICES.clear()
    SERVICE_ORDER.clear()

    for key in order_keys:
        svc = raw_data[key]
        if isinstance(svc, dict) and "name" in svc:
            SERVICES[key] = svc
            if key not in SERVICE_ORDER:
                SERVICE_ORDER.append(key)

    # Set standard services (filter to only valid keys)
    _standard_services = [k for k in standard_keys if k in SERVICE_ORDER]


def validate_service(svc, required_fields=None):
    """Validate a service dict has the required fields.

    Args:
        svc: Service dict to validate.
        required_fields: List of required field names. Defaults to standard set.

    Returns:
        bool: True if valid.
    """
    if not isinstance(svc, dict):
        return False
    if "name" not in svc or "command" not in svc:
        return False
    if required_fields:
        for field in required_fields:
            if field not in svc:
                return False
    return True


def add_service(key, service_dict, services_file=None):
    """Add a new service to SERVICES and persist.

    Args:
        key: Service identifier (e.g. 'storm').
        service_dict: Dict with at least name, port, tmux_session, log_file, command.
        services_file: Path for persistence. Uses default if None.

    Returns:
        bool: True on success.
    """
    global SERVICE_ORDER, _standard_services

    # Load current state
    data = load_services(services_file) if services_file else dict(_SERVICES_RAW)
    build_services(data)

    SERVICES[key] = service_dict
    if key not in SERVICE_ORDER:
        SERVICE_ORDER.append(key)

    save_services(services_file)
    return True


def edit_service(key, updates, services_file=None):
    """Update an existing service's fields and persist.

    Args:
        key: Service identifier to update.
        updates: Dict of fields to change (e.g. {'name': 'New Name'}).
        services_file: Path for persistence. Uses default if None.

    Returns:
        bool: True if service existed and was updated.
    """
    global SERVICE_ORDER, _standard_services

    data = load_services(services_file) if services_file else dict(_SERVICES_RAW)
    build_services(data)

    if key not in SERVICES:
        return False

    SERVICES[key].update(updates)
    save_services(services_file)
    return True


def delete_service(key, services_file=None):
    """Remove a service and persist.

    Args:
        key: Service identifier to remove.
        services_file: Path for persistence. Uses default if None.

    Returns:
        bool: True if service existed and was deleted.
    """
    global SERVICE_ORDER, _standard_services

    data = load_services(services_file) if services_file else dict(_SERVICES_RAW)
    build_services(data)

    if key not in SERVICES:
        return False

    del SERVICES[key]
    SERVICE_ORDER.remove(key)
    if key in _standard_services:
        _standard_services.remove(key)

    save_services(services_file)
    return True


def reorder_services(new_order, services_file=None):
    """Reorder services and persist.

    Args:
        new_order: List of service keys in desired order.
        services_file: Path for persistence. Uses default if None.

    Returns:
        bool: True on success.
    """
    global SERVICE_ORDER

    data = load_services(services_file) if services_file else dict(_SERVICES_RAW)
    build_services(data)

    SERVICE_ORDER.clear()
    SERVICE_ORDER.extend(new_order)

    save_services(services_file)
    return True


def cycle_layout_mode(current_idx, modes=None):
    """Cycle to next layout mode.

    Args:
        current_idx: Current layout index (0-based).
        modes: List of layout mode strings. Defaults to ["2cols", "2rows"].

    Returns:
        tuple: (new_index, new_mode)
    """
    if modes is None:
        modes = ["2cols", "2rows"]
    new_idx = (current_idx + 1) % len(modes)
    return new_idx, modes[new_idx]


# ── Module-level initialization (for launcher.py compatibility) ────────

# When imported by launcher.py, these are populated at import time.
_SERVICES_RAW = load_services()
build_services(_SERVICES_RAW)
