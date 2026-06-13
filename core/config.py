"""
core/config.py
Manages config.json (agent name, ports, logging — needed at process startup)
and merges it with DB-backed config (ERP, sync, enrollment — see core/database.py)
into a single config dict used throughout the app.
"""
import json
import logging
from pathlib import Path

log = logging.getLogger("zk_agent")

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

# Defaults used to create config.json if it doesn't exist.
# These match the project's original config.json values.
DEFAULT_FILE_CONFIG = {
    "agent": {
        "name": "Betterschool Attendance Agent",
        "adms_port": 5836,
        "web_port": 5837
    },
    "logging": {
        "level": "INFO",
        "file": "agent.log",
        "max_bytes": 5242880,
        "backup_count": 3
    }
}


def ensure_config_file() -> dict:
    """Create config.json with default values if missing. Returns the file config."""
    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_FILE_CONFIG, f, indent=2)
        return json.loads(json.dumps(DEFAULT_FILE_CONFIG))
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    # Backfill any missing top-level sections/keys with defaults
    changed = False
    for section, defaults in DEFAULT_FILE_CONFIG.items():
        if section not in cfg:
            cfg[section] = defaults
            changed = True
        elif isinstance(defaults, dict):
            for k, v in defaults.items():
                if k not in cfg[section]:
                    cfg[section][k] = v
                    changed = True
    if changed:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    return cfg


def load_file_config() -> dict:
    """Load config.json (agent/adms_port/web_port/logging). Creates it if missing."""
    return ensure_config_file()


def save_file_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def get_full_config() -> dict:
    """
    Returns the merged config dict: agent/logging from config.json,
    erp/sync/enrollment/onboarding_complete from the database.
    """
    from core.database import get_config_all
    cfg = load_file_config()
    cfg.update(get_config_all())
    return cfg