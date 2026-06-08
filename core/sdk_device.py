"""
core/sdk_device.py
Handles ZKTeco devices via pyzk (LAN/TCP/UDP SDK protocol).
"""
import logging
from core.database import (
    upsert_attendance, update_device_seen, db_log, get_device
)

log = logging.getLogger("zk_agent")

try:
    from zk import ZK
    ZK_AVAILABLE = True
except ImportError:
    ZK_AVAILABLE = False
    log.warning("pyzk not installed — SDK devices will not work. Run: pip install pyzk")


def _connect(device: dict):
    if not ZK_AVAILABLE:
        raise RuntimeError("pyzk is not installed. Run: pip install pyzk")
    zk = ZK(
        device["ip"],
        port=device.get("port", 4370),
        timeout=10,
        password=device.get("password", 0),
        force_udp=bool(device.get("force_udp", 0)),
        ommit_ping=bool(device.get("omit_ping", 1)),
    )
    return zk, zk.connect()


def check_status(device: dict) -> dict:
    try:
        zk, conn = _connect(device)
        info = {
            "connected": True,
            "firmware":  conn.get_firmware_version(),
            "serial":    conn.get_serialnumber(),
            "platform":  conn.get_platform(),
            "name":      conn.get_device_name(),
            "users":     len(conn.get_users()),
            "records":   len(conn.get_attendance()),
            "time":      str(conn.get_time()),
        }
        conn.disconnect()
        update_device_seen(info["serial"], firmware=info["firmware"])
        return info
    except Exception as e:
        return {"connected": False, "error": str(e)}


def pull_attendance(device: dict) -> int:
    """Pull attendance from SDK device, store in local DB. Returns inserted count."""
    db_log("INFO", f"[SDK] Pulling attendance from device: {device['name']} ({device['ip']})")
    try:
        zk, conn = _connect(device)
        records_raw = conn.get_attendance()
        serial = None
        try:
            serial = conn.get_serialnumber()
        except Exception:
            serial = device.get("serial") or device["ip"]
        conn.disconnect()

        records = [
            {
                "user_id":   str(r.user_id),
                "timestamp": str(r.timestamp),
                "status":    getattr(r, "status", 0),
                "punch":     getattr(r, "punch", 0),
                "raw":       f"{r.user_id}\t{r.timestamp}",
            }
            for r in records_raw
        ]

        inserted = upsert_attendance(records, device_id=device["id"], device_serial=serial)
        db_log("INFO", f"[SDK] {device['name']}: pulled {len(records)}, inserted {inserted} new")
        update_device_seen(serial)
        return inserted

    except Exception as e:
        db_log("ERROR", f"[SDK] {device['name']} pull failed: {e}")
        raise


def get_users(device: dict) -> list:
    zk, conn = _connect(device)
    try:
        users = conn.get_users()
        return [
            {
                "uid":       u.uid,
                "user_id":   u.user_id,
                "name":      u.name,
                "privilege": u.privilege,
                "card":      u.card,
            }
            for u in users
        ]
    finally:
        conn.disconnect()


def set_user_enabled(device: dict, uid: int, user_data: dict, enabled: bool):
    zk, conn = _connect(device)
    try:
        conn.set_user(
            uid=uid,
            name=user_data.get("name", ""),
            privilege=user_data.get("privilege", 0),
            password=user_data.get("password", ""),
            group_id=user_data.get("group_id", ""),
            user_id=str(user_data.get("user_id", uid)),
            card=user_data.get("card", 0),
            disabled=not enabled,
        )
        action = "enabled" if enabled else "disabled"
        db_log("INFO", f"[SDK] User uid={uid} {action} on {device['name']}")
    finally:
        conn.disconnect()