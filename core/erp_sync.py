"""
core/erp_sync.py
Pushes attendance to ERP, pulls commands, sends heartbeat.
"""
import logging
import requests
from core.database import (
    get_unsynced, mark_synced,
    start_sync_record, finish_sync_record,
    db_log, get_devices
)

log = logging.getLogger("zk_agent")


def _build_url(cfg: dict, endpoint_key: str, **kwargs) -> str:
    base     = cfg["erp"]["base_url"].rstrip("/")
    endpoint = cfg["erp"]["endpoints"].get(endpoint_key, "")
    for k, v in kwargs.items():
        endpoint = endpoint.replace("{" + k + "}", str(v))
    return base + endpoint


def _session(cfg: dict) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {cfg['erp']['token']}",
        "Content-Type":  "application/json",
    })
    return s


def push_attendance(cfg: dict) -> dict:
    """Push unsynced records to ERP. Returns summary dict."""
    batch_size = cfg["sync"].get("batch_size", 100)
    rows       = get_unsynced(batch_size)
    sync_id    = start_sync_record()

    if not rows:
        finish_sync_record(sync_id, 0, 0, 0, "success", "No new records")
        db_log("INFO", "[SYNC] No unsynced records to push")
        return {"pushed": 0, "message": "No new records to sync"}

    payload = [
        {
            "device_serial": r["device_serial"],
            "user_id":       r["user_id"],
            "timestamp":     r["timestamp"],
            "status":        r["status"],
            "punch":         r["punch"],
        }
        for r in rows
    ]

    url = _build_url(cfg, "push_attendance")
    db_log("INFO", f"[SYNC] Pushing {len(rows)} records to ERP → {url}")

    try:
        resp = _session(cfg).post(url, json=payload, timeout=20)
        resp.raise_for_status()
        ids = [r["id"] for r in rows]
        mark_synced(ids)
        finish_sync_record(sync_id, len(rows), len(rows), 0, "success", "OK")
        db_log("INFO", f"[SYNC] ✓ Pushed {len(rows)} records successfully")
        return {"pushed": len(rows), "message": f"Pushed {len(rows)} records"}
    except requests.RequestException as e:
        finish_sync_record(sync_id, len(rows), 0, len(rows), "failed", str(e))
        db_log("ERROR", f"[SYNC] ✗ ERP push failed: {e}")
        return {"pushed": 0, "message": f"ERP error: {e}"}


def pull_commands(cfg: dict) -> list:
    """Fetch pending commands from ERP (enable/disable users, etc.)."""
    url = _build_url(cfg, "pull_commands")
    try:
        resp = _session(cfg).get(url, timeout=10)
        resp.raise_for_status()
        commands = resp.json()
        if commands:
            db_log("INFO", f"[SYNC] Fetched {len(commands)} command(s) from ERP")
        return commands
    except Exception as e:
        db_log("WARN", f"[SYNC] Could not fetch commands: {e}")
        return []


def ack_command(cfg: dict, command_id, success: bool = True, message: str = ""):
    url = _build_url(cfg, "ack_command", id=command_id)
    try:
        _session(cfg).post(url, json={"success": success, "message": message}, timeout=5)
        db_log("INFO", f"[CMD] Acked command {command_id} — success={success}")
    except Exception as e:
        db_log("WARN", f"[SYNC] Could not ack command {command_id}: {e}")


def send_heartbeat(cfg: dict):
    """Notify ERP this agent is alive."""
    url = _build_url(cfg, "heartbeat")
    devices = get_devices()
    try:
        _session(cfg).post(url, json={
            "agent_name":    cfg["agent"]["name"],
            "device_count":  len(devices),
            "adms_port":     cfg["agent"]["adms_port"],
        }, timeout=5)
    except Exception:
        pass  # heartbeat failure is non-critical


def execute_commands(cfg: dict, commands: list) -> None:
    """
    Execute commands received from ERP against local SDK devices.
    Each command is acked (success or failure) after execution.
    Supported actions: register_user, delete_user, enable_user, disable_user.
    """
    if not commands:
        return

    from core import sdk_device
    from core.database import get_devices

    sdk_devices = [d for d in get_devices(enabled_only=True) if d["type"] == "sdk"]

    for cmd in commands:
        cmd_id = cmd.get("id")
        action  = cmd.get("action")
        payload = cmd.get("payload", {})

        if not cmd_id or not action:
            db_log("WARN", f"[CMD] Skipping malformed command: {cmd}")
            continue

        db_log("INFO", f"[CMD] Executing '{action}' for user_id={payload.get('user_id')} (cmd {cmd_id})")

        if not sdk_devices:
            db_log("WARN", f"[CMD] No enabled SDK devices — acking '{action}' without applying")
            continue

        applied = 0
        errors  = []

        for device in sdk_devices:
            try:
                if action == "register_user":
                    _cmd_register_user(device, payload)
                    applied += 1

                elif action == "delete_user":
                    _cmd_delete_user(device, payload)
                    applied += 1

                elif action in ("enable_user", "disable_user"):
                    enabled = (action == "enable_user")
                    _cmd_set_user_enabled(device, payload, enabled)
                    applied += 1

                else:
                    db_log("WARN", f"[CMD] Unknown action '{action}' — skipping device {device['name']}")

            except Exception as e:
                err = f"{device['name']}: {e}"
                errors.append(err)
                db_log("ERROR", f"[CMD] '{action}' failed on {device['name']}: {e}")

        if errors:
            msg = f"Applied to {applied} device(s). Errors: {'; '.join(errors)}"
            ack_command(cfg, cmd_id, success=(applied > 0), message=msg)
        else:
            ack_command(cfg, cmd_id, success=True,
                        message=f"Applied to {applied} device(s)")


def _cmd_register_user(device: dict, payload: dict):
    """Write user record on device. Enrollment is now triggered separately via WebSocket."""
    from core import sdk_device
    zk, conn = sdk_device._connect(device)
    try:
        uid = None
        try:
            existing = conn.get_users()
            for u in existing:
                if str(u.user_id) == str(payload.get("user_id")):
                    uid = u.uid
                    break
        except Exception:
            pass

        conn.set_user(
            uid=uid,
            name=payload.get("name", ""),
            privilege=int(payload.get("privilege", 0)),
            password=str(payload.get("password", "")),
            group_id="",
            user_id=str(payload.get("user_id", "")),
            card=int(payload.get("card", 0)),
        )
        db_log("INFO", f"[CMD] register_user user_id={payload.get('user_id')} on {device['name']}")

    finally:
        conn.disconnect()


def _cmd_delete_user(device: dict, payload: dict):
    """Delete a user from a device by user_id."""
    from core import sdk_device
    zk, conn = sdk_device._connect(device)
    try:
        existing = conn.get_users()
        target = None
        for u in existing:
            if str(u.user_id) == str(payload.get("user_id")):
                target = u
                break
        if target:
            conn.delete_user(uid=target.uid)
            db_log("INFO", f"[CMD] delete_user uid={target.uid} user_id={payload.get('user_id')} on {device['name']}")
        else:
            db_log("INFO", f"[CMD] delete_user — user_id={payload.get('user_id')} not found on {device['name']} (already absent)")
    finally:
        conn.disconnect()


def _cmd_set_user_enabled(device: dict, payload: dict, enabled: bool):
    """Enable or disable a user on a device."""
    from core import sdk_device
    zk, conn = sdk_device._connect(device)
    try:
        existing = conn.get_users()
        target = None
        for u in existing:
            if str(u.user_id) == str(payload.get("user_id")):
                target = u
                break
        if target:
            conn.set_user(
                uid=target.uid,
                name=payload.get("name", target.name),
                privilege=int(payload.get("privilege", target.privilege)),
                password=str(payload.get("password", "")),
                group_id="",
                user_id=str(payload.get("user_id", target.user_id)),
                card=int(payload.get("card", target.card or 0)),
                disabled=not enabled,
            )
            action_str = "enabled" if enabled else "disabled"
            db_log("INFO", f"[CMD] {action_str} user_id={payload.get('user_id')} on {device['name']}")
        else:
            db_log("WARN", f"[CMD] enable/disable — user_id={payload.get('user_id')} not found on {device['name']}")
    finally:
        conn.disconnect()


def full_sync(cfg: dict) -> dict:
    """Pull attendance from SDK devices, push to ERP, pull & execute commands."""
    from core import sdk_device
    from core.database import get_devices

    result = {"sdk_pulled": 0, "pushed": 0, "errors": []}

    # Pull attendance from all enabled devices that support SDK (type=sdk,
    # OR type=adms devices that also have an IP configured for SDK polling).
    all_devices = get_devices(enabled_only=True)
    sdk_pullable = [
        d for d in all_devices
        if d["type"] == "sdk"                          # pure SDK device
        or (d["type"] == "adms" and d.get("ip"))       # ADMS+SDK dual-mode
    ]

    for device in sdk_pullable:
        try:
            db_log("INFO", f"[SYNC] Pulling attendance from {device['name']} (type={device['type']})")
            inserted = sdk_device.pull_attendance(device)
            result["sdk_pulled"] += inserted
        except Exception as e:
            err = f"SDK pull failed for {device['name']}: {e}"
            result["errors"].append(err)
            db_log("ERROR", f"[SYNC] {err}")

    # Push all unsynced (SDK + ADMS) records to ERP
    push_result = push_attendance(cfg)
    result["pushed"] = push_result["pushed"]

    # Pull commands from ERP and execute them on devices
    commands = pull_commands(cfg)
    if commands:
        execute_commands(cfg, commands)
        result["commands_executed"] = len(commands)

    send_heartbeat(cfg)
    return result