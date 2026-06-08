"""
main.py
Entry point — initialises DB, starts ADMS server, web UI, and scheduler.
Run: python main.py
"""
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print("config.json not found. Copy config.example.json and fill in your details.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def setup_logging(cfg: dict):
    log_cfg = cfg.get("logging", {})
    level   = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    fmt     = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(level)

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Rotating file
    log_file = BASE_DIR / log_cfg.get("file", "agent.log")
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=log_cfg.get("max_bytes", 5_242_880),
        backupCount=log_cfg.get("backup_count", 3),
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Silence noisy libs
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main():
    cfg = load_config()
    setup_logging(cfg)
    log = logging.getLogger("zk_agent")

    log.info("=" * 50)
    log.info(f"Starting {cfg['agent']['name']}")
    log.info("=" * 50)

    # Init database
    from core.database import init_db
    init_db()
    log.info("Database initialised")

    # Start ADMS receiver
    from core.adms_server import start_adms_server
    start_adms_server(cfg["agent"]["adms_port"])

    # Start scheduler
    from core.scheduler import start_scheduler
    start_scheduler(cfg)

    # Start WebSocket client if sync_mode is realtime
    if cfg["sync"].get("sync_mode") == "realtime":
        from core.socket_client import start_socket_client
        start_socket_client(cfg)
        log.info("WebSocket client started (sync_mode=realtime)")
    else:
        log.info(f"WebSocket client not started (sync_mode={cfg['sync'].get('sync_mode', 'timely')})")

    # Start web UI (blocking — must be last)
    from web.server import start_web_server
    start_web_server(cfg)


if __name__ == "__main__":
    main()