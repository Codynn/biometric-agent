"""
tray.py
Entry point for the packaged agent.
- Starts all background services (ADMS, scheduler, WebSocket, web UI)
- Shows a system tray icon with status and right-click menu
"""
import logging
import logging.handlers
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ── Resolve BASE_DIR (read-only install dir, where the exe lives) ─────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

# ── DATA_DIR: writable directory for DB, logs, config ────────────────────────
# Program Files is read-only for non-admin processes, so we MUST use APPDATA.
# %APPDATA%\BiometricAgent  (~\AppData\Roaming\BiometricAgent)
DATA_DIR = Path(os.environ.get("APPDATA", str(BASE_DIR))) / "BiometricAgent"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Make sure our own packages are importable
sys.path.insert(0, str(BASE_DIR))

# Set working directory to DATA_DIR so any code that uses relative paths
# for DB/config/logs also lands in the writable location.
os.chdir(DATA_DIR)


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

    if not root.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    # Log file goes in DATA_DIR, not BASE_DIR
    log_file = DATA_DIR / log_cfg.get("file", "agent.log")
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=log_cfg.get("max_bytes", 5_242_880),
        backupCount=log_cfg.get("backup_count", 3),
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ── Service state ─────────────────────────────────────────────────────────────
class ServiceState:
    def __init__(self):
        self._lock             = threading.Lock()
        self.adms_running      = False
        self.scheduler_running = False
        self.websocket_running = False
        self.web_running       = False
        self.web_port          = 5837
        self.startup_error     = None

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


STATE     = ServiceState()
_stop_evt = threading.Event()


# ── Agent bootstrap ───────────────────────────────────────────────────────────
def start_agent():
    log = logging.getLogger("zk_agent")
    try:
        from core.config import load_file_config, get_full_config
        file_cfg = load_file_config()
        setup_logging(file_cfg)

        log.info("=" * 50)
        log.info(f"Starting {file_cfg['agent']['name']} (tray mode)")
        log.info(f"BASE_DIR : {BASE_DIR}")
        log.info(f"DATA_DIR : {DATA_DIR}")
        log.info("=" * 50)

        from core.database import init_db
        init_db()
        log.info("Database initialised")

        cfg      = get_full_config()
        web_port = cfg["agent"].get("web_port", 5837)
        STATE.set(web_port=web_port)

        from core.adms_server import start_adms_server
        start_adms_server(cfg["agent"]["adms_port"])
        STATE.set(adms_running=True)
        log.info("ADMS server started")

        from core.scheduler import start_scheduler
        start_scheduler(cfg)
        STATE.set(scheduler_running=True)
        log.info("Scheduler started")

        if cfg["sync"].get("sync_mode") == "realtime":
            from core.socket_client import start_socket_client
            start_socket_client(cfg)
            STATE.set(websocket_running=True)
            log.info("WebSocket client started")

        def _run_web():
            try:
                from web.server import start_web_server
                STATE.set(web_running=True)
                start_web_server(cfg)
            except Exception as exc:
                logging.getLogger("zk_agent").exception(f"Web server error: {exc}")
                STATE.set(web_running=False, startup_error=str(exc))

        threading.Thread(target=_run_web, daemon=True, name="web-ui").start()
        log.info(f"Web UI thread started on port {web_port}")

    except Exception as e:
        logging.getLogger("zk_agent").exception(f"Agent startup error: {e}")
        STATE.set(startup_error=str(e))


# ── Tray ──────────────────────────────────────────────────────────────────────
def _status_label(name: str, ok: bool) -> str:
    return f"  {'●' if ok else '○'} {name}: {'Running' if ok else 'Stopped'}"


def build_menu(pystray_mod, snap):
    from pystray import MenuItem as Item, Menu

    def open_panel(*_):
        webbrowser.open(f"http://127.0.0.1:{STATE.web_port}")

    def restart_agent(*_):
        import subprocess
        exe = sys.argv[0] if getattr(sys, "frozen", False) else sys.executable
        args = [exe] if getattr(sys, "frozen", False) else [exe] + sys.argv
        subprocess.Popen(args)
        os._exit(0)

    def exit_agent(*_):
        os._exit(0)

    s = snap
    items = [
        Item("Biometric Attendance Agent", None, enabled=False),
        Menu.SEPARATOR,
        Item("Open Web Panel", open_panel, default=True),
        Menu.SEPARATOR,
        Item(_status_label("ADMS Server", s["adms"]),      None, enabled=False),
        Item(_status_label("Scheduler",   s["scheduler"]), None, enabled=False),
        Item(_status_label("WebSocket",   s["websocket"]), None, enabled=False),
        Item(_status_label("Web UI",      s["web"]),       None, enabled=False),
    ]
    if s.get("startup_error"):
        # Truncate to fit tray menu width
        err = s["startup_error"][:70]
        items.append(Item(f"  ! {err}", None, enabled=False))

    items += [Menu.SEPARATOR, Item("Restart", restart_agent), Item("Exit", exit_agent)]
    return Menu(*items)


def run_tray():
    import pystray
    from PIL import Image

    icon_path = BASE_DIR / "assets" / "icon.ico"
    image = Image.open(icon_path) if icon_path.exists() else \
            Image.new("RGB", (64, 64), color=(34, 139, 34))

    icon = pystray.Icon("BiometricAgent", image, "Biometric Attendance Agent")
    icon.menu = build_menu(pystray, STATE.snapshot())

    def _refresh():
        while not _stop_evt.is_set():
            try:
                icon.menu = build_menu(pystray, STATE.snapshot())
                icon.update_menu()
            except Exception:
                pass
            time.sleep(5)

    threading.Thread(target=start_agent,  daemon=True, name="agent-init").start()
    threading.Thread(target=_refresh,     daemon=True, name="menu-refresh").start()
    icon.run()


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    run_tray()