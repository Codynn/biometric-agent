"""
web/server.py
Starts the Flask web UI server.
"""
import logging
from pathlib import Path
from flask import Flask, send_from_directory

from web.api import api_bp

log = logging.getLogger("zk_agent")

TEMPLATES_DIR = Path(__file__).parent / "templates"

web_app = Flask("web_ui", template_folder=str(TEMPLATES_DIR))
web_app.register_blueprint(api_bp, url_prefix="/api")


@web_app.route("/", defaults={"path": ""})
@web_app.route("/<path:path>")
def serve_ui(path):
    return send_from_directory(str(TEMPLATES_DIR), "index.html")


def start_web_server(cfg: dict):
    port = cfg["agent"].get("web_port", 5837)
    host = "0.0.0.0"
    log.info(f"Web UI available at http://127.0.0.1:{port}")
    web_app.run(host=host, port=port, debug=False, use_reloader=False)
