"""
main.py
Entry point — initialises DB, starts ADMS server, web UI, and scheduler.
Run: python main.py
"""
import logging
import logging.handlers
from pathlib import Path

from core.config import load_file_config, get_full_config

BASE_DIR = Path(__file__).parent


def setup_logging(file_cfg: dict):
    log_cfg = file_cfg.get("logging", {})
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
    # config.json (agent name, ports, logging) — created with defaults if missing
    file_cfg = load_file_config()
    setup_logging(file_cfg)
    log = logging.getLogger("zk_agent")

    log.info("=" * 50)
    log.info(f"Starting {file_cfg['agent']['name']}")
    log.info("=" * 50)

    # Init database (also seeds DB-backed config defaults)
    from core.database import init_db
    init_db()
    log.info("Database initialised")

    # Merged config: agent/logging from config.json + erp/sync/enrollment from DB
    cfg = get_full_config()

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