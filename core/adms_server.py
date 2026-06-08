"""
core/adms_server.py
Embedded Flask HTTP server that ZKTeco ADMS devices push attendance to.
Runs on a configurable port (default 5836).
"""
import logging
import threading
from flask import Flask, request

from core.database import (
    upsert_attendance, update_device_seen,
    get_device_by_serial, db_log
)

log = logging.getLogger("zk_agent")
adms_app = Flask("adms")
adms_app.logger.disabled = True
log.getChild("werkzeug").setLevel(logging.ERROR)

import logging as _logging
_logging.getLogger("werkzeug").setLevel(_logging.ERROR)


# ── Helpers ───────────────────────────────────────────────

def _parse_logs(body: str) -> list:
    if not body:
        return []
    records = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        records.append({
            "user_id":   parts[0].strip(),
            "timestamp": parts[1].strip(),
            "status":    int(parts[2]) if parts[2].strip().isdigit() else 0,
            "punch":     int(parts[3]) if parts[3].strip().isdigit() else 0,
            "raw":       line,
        })
    return records


def _parse_device_info(info: str) -> dict:
    parts = info.split(",")
    return {
        "firmware": parts[0].replace("Ver ", "").strip() if parts else None,
        "local_ip": parts[4].strip() if len(parts) > 4 else None,
    }


# ── Routes ────────────────────────────────────────────────

@adms_app.route("/iclock/cdata", methods=["GET"])
def handshake():
    sn = request.args.get("SN", "")
    pushver = request.args.get("pushver", "")
    db_log("INFO", f"[ADMS] Handshake — SN={sn} pushver={pushver}")
    return "\n".join([
        f"GET OPTION FROM: {sn}",
        "Stamp=9999",
        "OpStamp=9999",
        "ErrorDelay=30",
        "Delay=10",
        "TransTimes=00:00;23:59",
        "TransInterval=1",
        "TransFlag=TransData AttLog",
        "TimeZone=6",
        "Realtime=1",
        "Encrypt=None",
        "ServerVer=2.4.0",
        "PushProtVer=2.4.0",
    ])


@adms_app.route("/iclock/cdata", methods=["POST"])
def receive_attendance():
    sn    = request.args.get("SN", "")
    table = request.args.get("table", "")

    # Read raw body regardless of Content-Type
    body = request.get_data(as_text=True)

    if table == "ATTLOG":
        records = _parse_logs(body)
        db_log("INFO", f"[ADMS] ATTLOG from SN={sn} — {len(records)} record(s)")

        for r in records:
            db_log("INFO",
                f"[ADMS]   user={r['user_id']} | {r['timestamp']} | "
                f"status={r['status']} | punch={r['punch']}")

        if records:
            device = get_device_by_serial(sn)
            device_id = device["id"] if device else None
            inserted = upsert_attendance(records, device_id=device_id, device_serial=sn)
            db_log("INFO", f"[ADMS] Stored {inserted} new record(s) from SN={sn}")

        update_device_seen(sn)
        return f"OK: {len(records)}"

    if table == "options":
        # Device sending its config — just acknowledge
        return "OK"

    db_log("INFO", f"[ADMS] POST /cdata table={table} SN={sn} (ignored)")
    return "OK"


@adms_app.route("/iclock/getrequest", methods=["GET"])
def get_request():
    sn   = request.args.get("SN", "")
    info = request.args.get("INFO", "")

    if info:
        parsed = _parse_device_info(info)
        db_log("INFO",
            f"[ADMS] Device info SN={sn} | FW={parsed['firmware']} | IP={parsed['local_ip']}")
        update_device_seen(sn,
            firmware=parsed.get("firmware"),
            local_ip=parsed.get("local_ip"))
    else:
        db_log("INFO", f"[ADMS] Command poll SN={sn}")

    # TODO: return queued commands here when command queue is implemented
    return "OK"


@adms_app.route("/iclock/devicecmd", methods=["POST"])
def device_cmd_ack():
    sn   = request.args.get("SN", "")
    body = request.get_data(as_text=True)
    db_log("INFO", f"[ADMS] Command ack SN={sn}: {body}")
    return "OK"


# ── Runner ────────────────────────────────────────────────

_adms_thread = None

def start_adms_server(port: int):
    global _adms_thread

    def run():
        db_log("INFO", f"[ADMS] Server listening on 0.0.0.0:{port}")
        adms_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    _adms_thread = threading.Thread(target=run, daemon=True, name="adms-server")
    _adms_thread.start()
    log.info(f"ADMS server started on port {port}")