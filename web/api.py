"""
web/api.py
REST API endpoints for the web UI.
"""
import json
import logging
from pathlib import Path
from flask import Blueprint, jsonify, request

log = logging.getLogger("zk_agent")
api_bp = Blueprint("api", __name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def _load_cfg() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _save_cfg(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Config ────────────────────────────────────────────────

@api_bp.get("/config")
def get_config():
    cfg = _load_cfg()
    # Mask token for display
    safe = json.loads(json.dumps(cfg))
    token = safe["erp"].get("token", "")
    if token and token != "your-agent-token-here":
        safe["erp"]["token"] = token[:6] + "…" + token[-4:]
    return jsonify(safe)


@api_bp.post("/config")
def save_config():
    data = request.json or {}
    cfg  = _load_cfg()

    # Agent settings
    if "agent_name" in data:
        cfg["agent"]["name"] = data["agent_name"]
    if "adms_port" in data:
        cfg["agent"]["adms_port"] = int(data["adms_port"])
    if "web_port" in data:
        cfg["agent"]["web_port"] = int(data["web_port"])

    # ERP settings
    if "erp_base_url" in data:
        cfg["erp"]["base_url"] = data["erp_base_url"].rstrip("/")
    if "erp_token" in data and data["erp_token"] and "…" not in data["erp_token"]:
        cfg["erp"]["token"] = data["erp_token"]

    # Sync settings
    if "sync_mode" in data:
        if data["sync_mode"] in ("manual", "timely", "realtime"):
            cfg["sync"]["sync_mode"] = data["sync_mode"]
    if "interval_seconds" in data:
        cfg["sync"]["interval_seconds"] = int(data["interval_seconds"])
    if "batch_size" in data:
        cfg["sync"]["batch_size"] = int(data["batch_size"])

    _save_cfg(cfg)
    return jsonify({"ok": True})


@api_bp.post("/config/test-erp")
def test_erp():
    cfg = _load_cfg()
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

    # Coerce integers
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
    cfg = _load_cfg()
    from core.erp_sync import full_sync
    try:
        result = full_sync(cfg)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@api_bp.post("/sync/toggle")
def toggle_auto_sync():
    cfg = _load_cfg()
    cfg["sync"]["auto_sync"] = not cfg["sync"].get("auto_sync", False)
    _save_cfg(cfg)
    return jsonify({"auto_sync": cfg["sync"]["auto_sync"]})


@api_bp.get("/sync/history")
def sync_history():
    from core.database import get_sync_history
    limit = int(request.args.get("limit", 30))
    return jsonify(get_sync_history(limit))


# ── Logs ──────────────────────────────────────────────────

@api_bp.get("/logs")
def get_logs():
    from core.database import get_logs
    limit = int(request.args.get("limit", 100))
    return jsonify(get_logs(limit))


# ── Dashboard stats ───────────────────────────────────────

# ── Sync mode ─────────────────────────────────────────────

@api_bp.get("/sync/mode")
def get_sync_mode():
    cfg = _load_cfg()
    return jsonify({
        "sync_mode":        cfg["sync"].get("sync_mode", "timely"),
        "interval_seconds": cfg["sync"].get("interval_seconds", 60),
    })


@api_bp.post("/sync/mode")
def set_sync_mode():
    data = request.json or {}
    mode = data.get("sync_mode")
    if mode not in ("manual", "timely", "realtime"):
        return jsonify({"error": "sync_mode must be: manual | timely | realtime"}), 400
    cfg = _load_cfg()
    cfg["sync"]["sync_mode"] = mode
    if "interval_seconds" in data:
        cfg["sync"]["interval_seconds"] = int(data["interval_seconds"])
    _save_cfg(cfg)
    return jsonify({"ok": True, "sync_mode": mode})


# ── Enrollment device settings ────────────────────────────

@api_bp.get("/enrollment/devices")
def get_enrollment_devices():
    cfg = _load_cfg()
    from core.database import get_devices
    enrollment_ids = cfg.get("enrollment", {}).get("device_ids", [])
    all_devices    = get_devices()
    return jsonify({
        "enrollment_device_ids": enrollment_ids,
        "devices": all_devices,
    })


@api_bp.post("/enrollment/devices")
def set_enrollment_devices():
    """Set which device IDs are used for fingerprint enrollment."""
    data = request.json or {}
    device_ids = data.get("device_ids", [])
    if not isinstance(device_ids, list):
        return jsonify({"error": "device_ids must be a list of integers"}), 400

    from core.database import get_device
    for did in device_ids:
        if not get_device(int(did)):
            return jsonify({"error": f"Device id={did} not found"}), 404

    cfg = _load_cfg()
    if "enrollment" not in cfg:
        cfg["enrollment"] = {}
    cfg["enrollment"]["device_ids"] = [int(i) for i in device_ids]
    _save_cfg(cfg)
    return jsonify({"ok": True, "device_ids": cfg["enrollment"]["device_ids"]})


@api_bp.get("/dashboard")
def dashboard():
    from core.database import (
        get_devices, get_attendance_stats, get_sync_history, get_logs
    )
    cfg     = _load_cfg()
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