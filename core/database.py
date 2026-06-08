"""
core/database.py
SQLite layer — devices, attendance logs, sync history, agent log.
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "agent.db"
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    if not getattr(_local, "conn", None):
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL CHECK(type IN ('sdk','adms')),
            ip          TEXT,
            port        INTEGER DEFAULT 4370,
            serial      TEXT UNIQUE,
            password    INTEGER DEFAULT 0,
            omit_ping   INTEGER DEFAULT 1,
            force_udp   INTEGER DEFAULT 0,
            enabled     INTEGER DEFAULT 1,
            firmware    TEXT,
            local_ip    TEXT,
            last_seen   TEXT,
            added_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id       INTEGER REFERENCES devices(id),
            device_serial   TEXT,
            user_id         TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            status          INTEGER DEFAULT 0,
            punch           INTEGER DEFAULT 0,
            synced          INTEGER DEFAULT 0,
            synced_at       TEXT,
            raw             TEXT,
            UNIQUE(device_serial, user_id, timestamp)
        );

        CREATE TABLE IF NOT EXISTS sync_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            total       INTEGER DEFAULT 0,
            pushed      INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'running',
            message     TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT DEFAULT (datetime('now','localtime')),
            level       TEXT DEFAULT 'INFO',
            message     TEXT NOT NULL
        );
    """)
    conn.commit()


# ── Devices ───────────────────────────────────────────────

def get_devices(enabled_only=False):
    conn = get_conn()
    if enabled_only:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM devices WHERE enabled=1 ORDER BY id").fetchall()]
    return [dict(r) for r in conn.execute(
        "SELECT * FROM devices ORDER BY id").fetchall()]


def get_device(device_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
    return dict(row) if row else None


def get_device_by_serial(serial: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM devices WHERE serial=?", (serial,)).fetchone()
    return dict(row) if row else None


def add_device(data: dict) -> int:
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO devices (name, type, ip, port, serial, password, omit_ping, force_udp, enabled)
        VALUES (:name, :type, :ip, :port, :serial, :password, :omit_ping, :force_udp, 1)
    """, data)
    conn.commit()
    return cur.lastrowid


def update_device(device_id: int, data: dict):
    conn = get_conn()
    fields = ", ".join(f"{k}=:{k}" for k in data)
    data["id"] = device_id
    conn.execute(f"UPDATE devices SET {fields} WHERE id=:id", data)
    conn.commit()


def delete_device(device_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
    conn.commit()


def update_device_seen(serial: str, firmware: str = None, local_ip: str = None):
    conn = get_conn()
    conn.execute("""
        UPDATE devices SET last_seen=datetime('now','localtime'),
        firmware=COALESCE(?, firmware),
        local_ip=COALESCE(?, local_ip)
        WHERE serial=?
    """, (firmware, local_ip, serial))
    conn.commit()


# ── Attendance ────────────────────────────────────────────

def upsert_attendance(records: list, device_id: int = None, device_serial: str = None) -> int:
    conn = get_conn()
    inserted = 0
    for r in records:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO attendance
                (device_id, device_serial, user_id, timestamp, status, punch, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (device_id, device_serial,
                  str(r.get("user_id")), str(r.get("timestamp")),
                  r.get("status", 0), r.get("punch", 0),
                  r.get("raw", "")))
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception as e:
            db_log("ERROR", f"upsert_attendance row error: {e}")
    conn.commit()
    return inserted


def get_unsynced(batch_size=100):
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM attendance WHERE synced=0 ORDER BY timestamp LIMIT ?",
        (batch_size,)).fetchall()]


def mark_synced(ids: list):
    if not ids:
        return
    conn = get_conn()
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE attendance SET synced=1, synced_at=datetime('now','localtime') WHERE id IN ({placeholders})",
        ids)
    conn.commit()


def get_attendance(limit=200, device_id=None, synced=None):
    conn = get_conn()
    query = "SELECT a.*, d.name as device_name FROM attendance a LEFT JOIN devices d ON a.device_id=d.id WHERE 1=1"
    params = []
    if device_id:
        query += " AND a.device_id=?"
        params.append(device_id)
    if synced is not None:
        query += " AND a.synced=?"
        params.append(int(synced))
    query += " ORDER BY a.timestamp DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_attendance_stats():
    conn = get_conn()
    total    = conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
    unsynced = conn.execute("SELECT COUNT(*) FROM attendance WHERE synced=0").fetchone()[0]
    today    = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE date(timestamp)=date('now','localtime')").fetchone()[0]
    return {"total": total, "unsynced": unsynced, "today": today}


# ── Sync History ──────────────────────────────────────────

def start_sync_record() -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO sync_history (started_at, status) VALUES (datetime('now','localtime'), 'running')")
    conn.commit()
    return cur.lastrowid


def finish_sync_record(sync_id: int, total: int, pushed: int, failed: int,
                        status: str, message: str = ""):
    conn = get_conn()
    conn.execute("""
        UPDATE sync_history SET finished_at=datetime('now','localtime'),
        total=?, pushed=?, failed=?, status=?, message=? WHERE id=?
    """, (total, pushed, failed, status, message, sync_id))
    conn.commit()


def get_sync_history(limit=30):
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM sync_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


# ── Agent Log ─────────────────────────────────────────────

def db_log(level: str, message: str):
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO agent_log (level, message) VALUES (?, ?)", (level, message))
        conn.execute(
            "DELETE FROM agent_log WHERE id NOT IN (SELECT id FROM agent_log ORDER BY id DESC LIMIT 500)")
        conn.commit()
    except Exception:
        pass


def get_logs(limit=100):
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM agent_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]