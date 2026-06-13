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
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
        candidates = [
            base / "_internal" / "web" / "templates",   # PyInstaller 6+ default
            base / "web" / "templates",
            base / "_internal" / "templates",
            base / "templates",
        ]
        for c in candidates:
            if (c / "index.html").exists():
                return c
        raise RuntimeError(
            "Cannot find templates dir. Searched:\n" +
            "\n".join(f"  {c}" for c in candidates)
        )
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