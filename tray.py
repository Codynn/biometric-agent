"""
tray.py
Entry point for the packaged agent.
- Starts all background services (ADMS, scheduler, WebSocket, web UI)
- Shows a system tray icon with status and right-click menu
- Replaces main.py as the thing the user/installer runs
"""
import logging
import logging.handlers
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ── Resolve base dir whether running as .py or frozen .exe ───────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

# Make sure our own packages are importable
sys.path.insert(0, str(BASE_DIR))

# ── CRITICAL: set working directory to BASE_DIR so all relative paths
#    (SQLite DB, config.json, log files) resolve correctly when the exe
#    is launched by the installer or the Run key from Program Files. ──────────
os.chdir(BASE_DIR)


# ── Logging ───────────────────────────────────────────────────────────────────
def setup_logging(file_cfg: dict):
    log_cfg = file_cfg.get("logging", {})
    level   = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    fmt     = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid adding duplicate handlers if called more than once
    if not root.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    log_file = BASE_DIR / log_cfg.get("file", "agent.log")
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=log_cfg.get("max_bytes", 5_242_880),
        backupCount=log_cfg.get("backup_count", 3),
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ── Service state (shared between agent threads and tray) ─────────────────────
class ServiceState:
    def __init__(self):
        self._lock             = threading.Lock()
        self.adms_running      = False
        self.scheduler_running = False
        self.websocket_running = False
        self.web_running       = False
        self.web_port          = 5837
        self.startup_error     = None   # holds exception message if startup fails

    def set(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def snapshot(self):
        with self._lock:
            return {
                "adms":          self.adms_running,
                "scheduler":     self.scheduler_running,
                "websocket":     self.websocket_running,
                "web":           self.web_running,
                "web_port":      self.web_port,
                "startup_error": self.startup_error,
            }


STATE = ServiceState()
_stop_event = threading.Event()


# ── Agent bootstrap ───────────────────────────────────────────────────────────
def start_agent():
    """Initialise DB, then start all services. Runs in its own thread."""
    log = logging.getLogger("zk_agent")
    try:
        from core.config import load_file_config, get_full_config
        file_cfg = load_file_config()
        setup_logging(file_cfg)

        log.info("=" * 50)
        log.info(f"Starting {file_cfg['agent']['name']} (tray mode)")
        log.info(f"BASE_DIR: {BASE_DIR}")
        log.info("=" * 50)

        from core.database import init_db
        init_db()
        log.info("Database initialised")

        cfg = get_full_config()
        web_port = cfg["agent"].get("web_port", 5837)
        STATE.set(web_port=web_port)

        # ADMS server
        from core.adms_server import start_adms_server
        start_adms_server(cfg["agent"]["adms_port"])
        STATE.set(adms_running=True)
        log.info("ADMS server started")

        # Scheduler
        from core.scheduler import start_scheduler
        start_scheduler(cfg)
        STATE.set(scheduler_running=True)
        log.info("Scheduler started")

        # WebSocket client (realtime mode only)
        if cfg["sync"].get("sync_mode") == "realtime":
            from core.socket_client import start_socket_client
            start_socket_client(cfg)
            STATE.set(websocket_running=True)
            log.info("WebSocket client started")

        # Web UI — runs in its own daemon thread so tray stays responsive
        def _run_web():
            try:
                from web.server import start_web_server
                STATE.set(web_running=True)
                start_web_server(cfg)
            except Exception as exc:
                logging.getLogger("zk_agent").exception(f"Web server error: {exc}")
                STATE.set(web_running=False, startup_error=str(exc))

        web_thread = threading.Thread(target=_run_web, daemon=True, name="web-ui")
        web_thread.start()
        log.info(f"Web UI thread started on port {web_port}")

    except Exception as e:
        logging.getLogger("zk_agent").exception(f"Agent startup error: {e}")
        STATE.set(startup_error=str(e))


# ── Tray icon ─────────────────────────────────────────────────────────────────
def _status_label(name: str, ok: bool) -> str:
    bullet = "●" if ok else "○"
    status = "Running" if ok else "Stopped"
    return f"  {bullet} {name}: {status}"


def build_menu(pystray, snapshot):
    from pystray import MenuItem as Item, Menu

    def open_panel(_icon, _item):
        webbrowser.open(f"http://127.0.0.1:{STATE.web_port}")

    def restart_agent(_icon, _item):
        """Restart the whole process (re-reads config from disk)."""
        import subprocess
        if getattr(sys, "frozen", False):
            exe = sys.argv[0]
            subprocess.Popen([exe])
        else:
            exe = sys.executable
            subprocess.Popen([exe] + sys.argv)
        _icon.stop()
        os._exit(0)

    def exit_agent(_icon, _item):
        _icon.stop()
        os._exit(0)

    s = snapshot
    items = [
        Item("Biometric Attendance Agent", None, enabled=False),
        Menu.SEPARATOR,
        Item("Open Web Panel", open_panel, default=True),
        Menu.SEPARATOR,
        Item(_status_label("ADMS Server",  s["adms"]),      None, enabled=False),
        Item(_status_label("Scheduler",    s["scheduler"]), None, enabled=False),
        Item(_status_label("WebSocket",    s["websocket"]), None, enabled=False),
        Item(_status_label("Web UI",       s["web"]),       None, enabled=False),
    ]

    if s.get("startup_error"):
        items.append(Item(f"  ⚠ Error: {s['startup_error'][:60]}", None, enabled=False))

    items += [
        Menu.SEPARATOR,
        Item("Restart", restart_agent),
        Item("Exit",    exit_agent),
    ]

    return Menu(*items)


def run_tray():
    import pystray
    from PIL import Image

    icon_path = BASE_DIR / "assets" / "icon.ico"

    if icon_path.exists():
        image = Image.open(icon_path)
    else:
        # Fallback: plain green square so the tray still works without an icon file
        image = Image.new("RGB", (64, 64), color=(34, 139, 34))

    icon = pystray.Icon(
        name="BiometricAgent",
        icon=image,
        title="Biometric Attendance Agent",
    )

    def refresh_menu():
        """Rebuild the menu every 5 s so status labels stay current."""
        while not _stop_event.is_set():
            try:
                snap = STATE.snapshot()
                icon.menu = build_menu(pystray, snap)
                icon.update_menu()
            except Exception:
                pass
            time.sleep(5)

    # Build initial menu
    icon.menu = build_menu(pystray, STATE.snapshot())

    # Start agent services in background
    agent_thread = threading.Thread(target=start_agent, daemon=True, name="agent-init")
    agent_thread.start()

    # Menu refresh thread
    refresh_thread = threading.Thread(target=refresh_menu, daemon=True, name="menu-refresh")
    refresh_thread.start()

    # Run tray (blocks until icon.stop() is called)
    icon.run()


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # On Windows, hide the console window when run as a windowed app
    if sys.platform == "win32":
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)

    run_tray()