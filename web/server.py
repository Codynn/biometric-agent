"""
web/server.py
Starts the Flask web UI server.
"""
import logging
import sys
from pathlib import Path
from flask import Flask, send_from_directory

from web.api import api_bp

log = logging.getLogger("zk_agent")


def _templates_dir() -> Path:
    """
    Find the templates folder whether we're frozen or running from source.

    PyInstaller COLLECT layout after  ("web/templates", "web/templates"):
        dist/BiometricAgent/
            BiometricAgent.exe
            web/
                templates/
                    index.html
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
        candidate = base / "web" / "templates"
        if candidate.exists():
            return candidate
        # Fallback: PyInstaller sometimes flattens — check one level up
        candidate2 = base / "templates"
        if candidate2.exists():
            return candidate2
        raise RuntimeError(
            f"Cannot find templates dir. Looked in:\n  {candidate}\n  {candidate2}\n"
            f"Dist contents: {list(base.iterdir())}"
        )
    # Running as plain .py — templates/ is next to this file (web/templates)
    return Path(__file__).parent / "templates"


TEMPLATES_DIR = _templates_dir()

web_app = Flask("web_ui", template_folder=str(TEMPLATES_DIR))
web_app.register_blueprint(api_bp, url_prefix="/api")


@web_app.route("/", defaults={"path": ""})
@web_app.route("/<path:path>")
def serve_ui(path):
    return send_from_directory(str(TEMPLATES_DIR), "index.html")


def start_web_server(cfg: dict):
    port = cfg["agent"].get("web_port", 5837)
    log.info(f"Templates dir : {TEMPLATES_DIR}")
    log.info(f"Web UI        : http://127.0.0.1:{port}")
    web_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)