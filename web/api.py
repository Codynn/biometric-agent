"""
web/api.py
REST API endpoints for the web UI.
"""
import json
import logging
import os
import sys
import threading
from flask import Blueprint, jsonify, request

from core.config import load_file_config, save_file_config, get_full_config

log = logging.getLogger("zk_agent")
api_bp = Blueprint("api", __name__)


# ── Config ────────────────────────────────────────────────

@api_bp.get("/config")
def get_config():
    cfg = get_full_config()
    # Mask token for display
    safe = json.loads(json.dumps(cfg))
    token = safe["erp"].get("token", "")
    if token:
        safe["erp"]["token"] = token[:6] + "..." + token[-4:] if len(token) > 10 else "......"
    return jsonify(safe)


@api_bp.post("/config")
def save_config():
    from core.database import set_config_section
    data = request.json or {}

    # config.json: agent name, ports, logging
    file_cfg = load_file_config()
    file_changed = False

    if "agent_name" in data:
        file_cfg["agent"]["name"] = data["agent_name"]
        file_changed = True
    if "adms_port" in data:
        file_cfg["agent"]["adms_port"] = int(data["adms_port"])
        file_changed = True
    if "web_port" in data:
        file_cfg["agent"]["web_port"] = int(data["web_port"])
        file_changed = True
    if "log_level" in data:
        file_cfg.setdefault("logging", {})["level"] = data["log_level"]
        file_changed = True

    if file_changed:
        save_file_config(file_cfg)

    # DB-backed config: ERP, sync, enrollment
    db_section = {}

    erp = {}
    if "erp_base_url" in data:
        erp["base_url"] = data["erp_base_url"].rstrip("/")
    if "erp_token" in data and data["erp_token"] and "..." not in data["erp_token"]:
        erp["token"] = data["erp_token"]
    if "erp_name" in data:
        erp["name"] = data["erp_name"]
    if erp:
        db_section["erp"] = erp

    sync = {}
    if "sync_mode" in data and data["sync_mode"] in ("manual", "timely", "realtime"):
        sync["sync_mode"] = data["sync_mode"]
    if "interval_seconds" in data:
        sync["interval_seconds"] = int(data["interval_seconds"])
    if "batch_size" in data:
        sync["batch_size"] = int(data["batch_size"])
    if "auto_sync" in data:
        sync["auto_sync"] = bool(data["auto_sync"])
    if sync:
        db_section["sync"] = sync

    if db_section:
        set_config_section(db_section)

    return jsonify({
        "ok": True,
        "restart_required": file_changed,
    })


@api_bp.post("/config/test-erp")
def test_erp():
    cfg = get_full_config()
    import requests as req
    url = cfg["erp"]["base_url"].rstrip("/") + cfg["erp"]["endpoints"]["heartbeat"]
    try:
        r = req.post(url, json={"agent_name": cfg["agent"]["name"], "test": True},
                     headers={"Authorization": f"Bearer {cfg['erp']['token']}",
                              "Content-Type": "application/json"},
                     timeout=8)
        return jsonify({"ok": r.ok, "status": r.status_code, "body": r.text[:200]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Onboarding ────────────────────────────────────────────

@api_bp.get("/onboarding/status")
def onboarding_status():
    from core.database import is_onboarding_complete
    return jsonify({"onboarding_complete": is_onboarding_complete()})


@api_bp.post("/onboarding")
def complete_onboarding():
    from core.database import set_config_section
    data = request.json or {}

    if "agent_name" in data:
        file_cfg = load_file_config()
        file_cfg["agent"]["name"] = data["agent_name"]
        save_file_config(file_cfg)

    erp_base_url = (data.get("erp_base_url") or "").rstrip("/")
    erp_token    = data.get("erp_token") or ""

    if not erp_base_url or not erp_token:
        return jsonify({"error": "ERP base URL and token are required"}), 400

    set_config_section({
        "erp": {"base_url": erp_base_url, "token": erp_token},
        "sync": {"sync_mode": data.get("sync_mode", "timely")},
        "onboarding_complete": True,
    })
    return jsonify({"ok": True})


# ── Restart ───────────────────────────────────────────────

@api_bp.post("/restart")
def restart_agent():
    """Restart the whole agent process so config.json changes take effect."""
    def _do_restart():
        import time, subprocess
        time.sleep(0.5)  # let the HTTP response flush first
        if getattr(sys, "frozen", False):
            # Frozen exe: spawn a new copy then exit this one
            subprocess.Popen([sys.argv[0]])
        else:
            # Plain Python: re-exec in place
            os.execv(sys.executable, [sys.executable] + sys.argv)
        os._exit(0)

    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"ok": True, "message": "Restarting..."})


# ── Devices ───────────────────────────────────────────────

@api_bp.get("/devices")
def list_devices():
    from core.database import get_devices
    return jsonify(get_devices())


@api_bp.post("/devices")
def add_device():
    data = request.json or {}
    required = ["name", "type"]
    for f in required:
        if not data.get(f):
            return jsonify({"error": f"'{f}' is required"}), 400
    if data["type"] not in ("sdk", "adms"):
        return jsonify({"error": "type must be 'sdk' or 'adms'"}), 400
    if data["type"] == "sdk" and not data.get("ip"):
        return jsonify({"error": "IP address required for SDK devices"}), 400

    from core.database import add_device
    device_id = add_device({
        "name":      data["name"],
        "type":      data["type"],
        "ip":        data.get("ip", ""),
        "port":      int(data.get("port", 4370)),
        "serial":    data.get("serial", ""),
        "password":  int(data.get("password", 0)),
        "omit_ping": int(data.get("omit_ping", 1)),
        "force_udp": int(data.get("force_udp", 0)),
    })
    from core.database import get_device
    return jsonify(get_device(device_id)), 201


@api_bp.put("/devices/<int:device_id>")
def update_device(device_id):
    from core.database import update_device as db_update, get_device
    device = get_device(device_id)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    data    = request.json or {}
    allowed = ["name", "ip", "port", "serial", "password",
               "omit_ping", "force_udp", "enabled"]
    update  = {k: data[k] for k in allowed if k in data}

    for int_field in ["port", "password", "omit_ping", "force_udp", "enabled"]:
        if int_field in update:
            update[int_field] = int(update[int_field])

    db_update(device_id, update)
    return jsonify(get_device(device_id))


@api_bp.delete("/devices/<int:device_id>")
def remove_device(device_id):
    from core.database import delete_device, get_device
    if not get_device(device_id):
        return jsonify({"error": "Device not found"}), 404
    delete_device(device_id)
    return jsonify({"ok": True})


@api_bp.post("/devices/<int:device_id>/test")
def test_device(device_id):
    from core.database import get_device
    device = get_device(device_id)
    if not device:
        return jsonify({"error": "Device not found"}), 404
    if device["type"] != "sdk":
        return jsonify({"error": "Connection test only supported for SDK devices"}), 400

    from core.sdk_device import check_status
    result = check_status(device)
    return jsonify(result)


@api_bp.post("/devices/<int:device_id>/pull")
def pull_device(device_id):
    from core.database import get_device
    device = get_device(device_id)
    if not device:
        return jsonify({"error": "Device not found"}), 404
    if device["type"] != "sdk":
        return jsonify({"error": "Manual pull only for SDK devices. ADMS devices push automatically."}), 400

    from core.sdk_device import pull_attendance
    try:
        inserted = pull_attendance(device)
        return jsonify({"ok": True, "inserted": inserted})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Attendance ────────────────────────────────────────────

@api_bp.get("/attendance")
def get_attendance():
    from core.database import get_attendance, get_attendance_stats
    limit     = int(request.args.get("limit", 200))
    device_id = request.args.get("device_id", type=int)
    synced    = request.args.get("synced")
    if synced is not None:
        synced = synced.lower() in ("1", "true")

    rows  = get_attendance(limit=limit, device_id=device_id, synced=synced)
    stats = get_attendance_stats()
    return jsonify({"stats": stats, "records": rows})


# ── Sync ──────────────────────────────────────────────────

@api_bp.post("/sync")
def trigger_sync():
    cfg = get_full_config()
    from core.erp_sync import full_sync
    try:
        result = full_sync(cfg)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@api_bp.post("/sync/toggle")
def toggle_auto_sync():
    from core.database import get_config_value, set_config_value
    current = get_config_value("sync.auto_sync", "false").lower() == "true"
    new_val = not current
    set_config_value("sync.auto_sync", str(new_val).lower())
    return jsonify({"auto_sync": new_val})


@api_bp.get("/sync/history")
def sync_history():
    from core.database import get_sync_history
    limit = int(request.args.get("limit", 30))
    return jsonify(get_sync_history(limit))


@api_bp.get("/sync/mode")
def get_sync_mode():
    cfg = get_full_config()
    return jsonify({
        "sync_mode":        cfg["sync"].get("sync_mode", "timely"),
        "interval_seconds": cfg["sync"].get("interval_seconds", 60),
    })


@api_bp.post("/sync/mode")
def set_sync_mode():
    from core.database import set_config_section
    data = request.json or {}
    mode = data.get("sync_mode")
    if mode not in ("manual", "timely", "realtime"):
        return jsonify({"error": "sync_mode must be: manual | timely | realtime"}), 400
    sync = {"sync_mode": mode}
    if "interval_seconds" in data:
        sync["interval_seconds"] = int(data["interval_seconds"])
    set_config_section({"sync": sync})
    return jsonify({"ok": True, "sync_mode": mode})


# ── Logs ──────────────────────────────────────────────────

@api_bp.get("/logs")
def get_logs():
    from core.database import get_logs
    limit = int(request.args.get("limit", 100))
    return jsonify(get_logs(limit))


# ── Enrollment ────────────────────────────────────────────

@api_bp.get("/enrollment/devices")
def get_enrollment_devices():
    cfg = get_full_config()
    from core.database import get_devices
    enrollment_ids = cfg.get("enrollment", {}).get("device_ids", [])
    all_devices    = get_devices()
    return jsonify({
        "enrollment_device_ids": enrollment_ids,
        "devices": all_devices,
    })


@api_bp.post("/enrollment/devices")
def set_enrollment_devices():
    from core.database import set_config_section
    data = request.json or {}
    device_ids = data.get("device_ids", [])
    if not isinstance(device_ids, list):
        return jsonify({"error": "device_ids must be a list of integers"}), 400

    from core.database import get_device
    for did in device_ids:
        if not get_device(int(did)):
            return jsonify({"error": f"Device id={did} not found"}), 404

    ids = [int(i) for i in device_ids]
    set_config_section({"enrollment": {"device_ids": ids}})
    return jsonify({"ok": True, "device_ids": ids})


# ── Dashboard ─────────────────────────────────────────────

@api_bp.get("/dashboard")
def dashboard():
    from core.database import (
        get_devices, get_attendance_stats, get_sync_history, get_logs
    )
    cfg     = get_full_config()
    devices = get_devices()
    stats   = get_attendance_stats()
    history = get_sync_history(5)
    logs    = get_logs(20)

    return jsonify({
        "agent_name":    cfg["agent"]["name"],
        "erp_url":       cfg["erp"]["base_url"],
        "auto_sync":     cfg["sync"].get("auto_sync", False),
        "interval":      cfg["sync"].get("interval_seconds", 60),
        "adms_port":     cfg["agent"]["adms_port"],
        "device_count":  len(devices),
        "sdk_count":     sum(1 for d in devices if d["type"] == "sdk"),
        "adms_count":    sum(1 for d in devices if d["type"] == "adms"),
        "attendance":    stats,
        "recent_syncs":  history,
        "recent_logs":   logs,
    })