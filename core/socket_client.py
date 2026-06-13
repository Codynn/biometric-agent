"""
core/socket_client.py
Socket.IO client — connects the agent to the ERP server.

Only started when sync_mode = "realtime" in config.json.

Events received from ERP:
  sync                → run full_sync immediately
  enroll_user         → trigger enrollment on enrollment device(s) only
  complete_enrollment → download template from enrollment device, push to all others

Events emitted to ERP:
  enrollment_ready    → enrollment triggered, person must place finger
  enrollment_synced   → template synced to all devices
  enrollment_error    → something went wrong during enroll or sync
"""
import logging
import threading

log = logging.getLogger("zk_agent")

_client_thread = None
_sio = None


def _load_cfg() -> dict:
    from core.config import get_full_config
    return get_full_config()


# ── Enrollment helpers ────────────────────────────────────

def _get_enrollment_devices(cfg: dict) -> list:
    """Return devices marked as enrollment devices in config."""
    from core.database import get_devices
    enrollment_ids = cfg.get("enrollment", {}).get("device_ids", [])
    if not enrollment_ids:
        # Fallback: use first enabled SDK device
        all_devices = [d for d in get_devices(enabled_only=True) if d["type"] == "sdk"]
        return all_devices[:1]
    all_devices = {d["id"]: d for d in get_devices(enabled_only=True)}
    return [all_devices[i] for i in enrollment_ids if i in all_devices]


def _get_non_enrollment_sdk_devices(cfg: dict) -> list:
    """Return all enabled SDK devices that are NOT enrollment devices."""
    from core.database import get_devices
    enrollment_ids = set(cfg.get("enrollment", {}).get("device_ids", []))
    return [
        d for d in get_devices(enabled_only=True)
        if d["type"] == "sdk" and d["id"] not in enrollment_ids
    ]


def _resolve_uid_on_device(conn, user_id: str):
    """Find the device uid for a given user_id string."""
    try:
        for u in conn.get_users():
            if str(u.user_id) == str(user_id):
                return u.uid
    except Exception:
        pass
    return None


# ── Event handlers ────────────────────────────────────────

def _handle_sync(data=None):
    """ERP requests an immediate sync — run full_sync in background thread."""
    from core.database import db_log
    db_log("INFO", "[WS] Received 'sync' event from ERP — running full_sync")

    def _run():
        try:
            cfg = _load_cfg()
            from core.erp_sync import full_sync
            result = full_sync(cfg)
            db_log("INFO",
                f"[WS] Sync complete — sdk_pulled={result['sdk_pulled']} "
                f"pushed={result['pushed']} errors={len(result['errors'])}")
        except Exception as e:
            db_log("ERROR", f"[WS] Sync error: {e}")

    threading.Thread(target=_run, daemon=True, name="ws-sync").start()


def _handle_enroll_user(data: dict):
    """
    ERP requests enrollment for a user.
    1. Trigger enroll_user on enrollment device(s) only.
    2. Emit enrollment_ready back to ERP.
    """
    from core.database import db_log
    from core import sdk_device

    user_id = str(data.get("user_id", ""))
    db_log("INFO", f"[WS] Received 'enroll_user' for user_id={user_id}")

    def _run():
        cfg = _load_cfg()
        enrollment_devices = _get_enrollment_devices(cfg)
        print("ENROLLMENT DEVICES::", enrollment_devices)
        if not enrollment_devices:
            db_log("ERROR", "[WS] enroll_user: no enrollment devices configured")
            if _sio and _sio.connected:
                _sio.emit("enrollment_error", {
                    "user_id": user_id,
                    "error": "No enrollment devices configured on agent."
                })
            return

        triggered = []
        errors    = []

        for device in enrollment_devices:
            try:
                zk, conn = sdk_device._connect(device)
                try:
                    uid = _resolve_uid_on_device(conn, user_id)
                    if uid is None:
                        # User not registered on device yet — register first
                        conn.set_user(
                            uid=None,
                            name=data.get("name", ""),
                            privilege=int(data.get("privilege", 0)),
                            password=str(data.get("password", "")),
                            group_id="",
                            user_id=user_id,
                            card=int(data.get("card", 0)),
                        )
                        db_log("INFO", f"[WS] Auto-registered user_id={user_id} on {device['name']} before enroll")
                        uid = _resolve_uid_on_device(conn, user_id)

                    if uid is not None:
                        conn.enroll_user(uid=uid)
                        triggered.append(device["name"])
                        db_log("INFO", f"[WS] enroll_user triggered uid={uid} on {device['name']}")
                    else:
                        errors.append(f"{device['name']}: could not resolve uid")
                finally:
                    conn.disconnect()
            except Exception as e:
                errors.append(f"{device['name']}: {e}")
                db_log("ERROR", f"[WS] enroll_user error on {device['name']}: {e}")

        if _sio and _sio.connected:
            if triggered:
                _sio.emit("enrollment_ready", {
                    "user_id":  user_id,
                    "devices":  triggered,
                    "message":  f"Enrollment triggered on: {', '.join(triggered)}. Ask user to place finger on device.",
                })
            else:
                _sio.emit("enrollment_error", {
                    "user_id": user_id,
                    "error":   "; ".join(errors) or "Unknown error",
                })

    threading.Thread(target=_run, daemon=True, name="ws-enroll").start()


def _handle_complete_enrollment(data: dict):
    """
    ERP signals enrollment is done (user placed finger).
    1. Download fingerprint template from enrollment device.
    2. Upload template to all other enabled SDK devices.
    3. Emit enrollment_synced back to ERP.
    """
    from core.database import db_log
    from core import sdk_device

    user_id = str(data.get("user_id", ""))
    db_log("INFO", f"[WS] Received 'complete_enrollment' for user_id={user_id}")

    def _run():
        cfg = _load_cfg()
        enrollment_devices     = _get_enrollment_devices(cfg)
        non_enrollment_devices = _get_non_enrollment_sdk_devices(cfg)

        if not enrollment_devices:
            db_log("ERROR", "[WS] complete_enrollment: no enrollment devices configured")
            if _sio and _sio.connected:
                _sio.emit("enrollment_error", {
                    "user_id": user_id,
                    "error":   "No enrollment devices configured on agent."
                })
            return

        # ── Step 1: Download template from enrollment device ──
        template     = None
        enroll_dev   = None
        uid_on_enroll = None

        for device in enrollment_devices:
            try:
                zk, conn = sdk_device._connect(device)
                try:
                    uid = _resolve_uid_on_device(conn, user_id)
                    if uid is None:
                        db_log("WARN", f"[WS] complete_enrollment: user_id={user_id} not found on {device['name']}")
                        continue
                    templates = conn.get_templates()
                    for t in templates:
                        if t.uid == uid:
                            template      = t
                            enroll_dev    = device
                            uid_on_enroll = uid
                            break
                    if template:
                        db_log("INFO", f"[WS] Template downloaded from {device['name']} uid={uid}")
                        break
                finally:
                    conn.disconnect()
            except Exception as e:
                db_log("ERROR", f"[WS] Template download error on {device['name']}: {e}")

        if template is None:
            db_log("ERROR", f"[WS] complete_enrollment: no template found for user_id={user_id}")
            if _sio and _sio.connected:
                _sio.emit("enrollment_error", {
                    "user_id": user_id,
                    "error":   "No fingerprint template found on enrollment device. Has the user enrolled their finger?"
                })
            return

        # ── Step 2: Upload template to all other SDK devices ──
        synced = []
        errors = []

        for device in non_enrollment_devices:
            try:
                zk, conn = sdk_device._connect(device)
                try:
                    # Ensure user record exists on target device first
                    uid_on_target = _resolve_uid_on_device(conn, user_id)
                    if uid_on_target is None:
                        conn.set_user(
                            uid=None,
                            name=data.get("name", ""),
                            privilege=int(data.get("privilege", 0)),
                            password=str(data.get("password", "")),
                            group_id="",
                            user_id=user_id,
                            card=int(data.get("card", 0)),
                        )
                        uid_on_target = _resolve_uid_on_device(conn, user_id)
                        db_log("INFO", f"[WS] Auto-registered user_id={user_id} on {device['name']} before template sync")

                    if uid_on_target is not None:
                        # Remap template uid to target device's uid
                        template.uid = uid_on_target
                        conn.save_user_template(
                            user=type("U", (), {"uid": uid_on_target})(),
                            template=template
                        )
                        synced.append(device["name"])
                        db_log("INFO", f"[WS] Template synced to {device['name']} uid={uid_on_target}")
                    else:
                        errors.append(f"{device['name']}: could not resolve uid after register")
                finally:
                    conn.disconnect()
            except Exception as e:
                errors.append(f"{device['name']}: {e}")
                db_log("ERROR", f"[WS] Template sync error on {device['name']}: {e}")

        if _sio and _sio.connected:
            _sio.emit("enrollment_synced", {
                "user_id":        user_id,
                "synced_devices": synced,
                "errors":         errors,
                "message":        f"Template synced to {len(synced)} device(s)."
                                  + (f" Errors: {'; '.join(errors)}" if errors else ""),
            })

        db_log("INFO",
            f"[WS] complete_enrollment done — synced={synced} errors={errors}")

    threading.Thread(target=_run, daemon=True, name="ws-complete-enroll").start()


# ── Connection management ─────────────────────────────────

def _build_erp_ws_url(cfg: dict) -> str:
    """Convert ERP base_url (HTTP) to WebSocket URL."""
    base = cfg["erp"]["base_url"].rstrip("/")
    # socket.io client handles ws:// upgrade automatically from http://
    return base


def _start_client(cfg: dict):
    global _sio
    import socketio as sio_lib
    from core.database import db_log

    token    = cfg["erp"]["token"]
    ws_url   = _build_erp_ws_url(cfg)

    _sio = sio_lib.Client(
        reconnection=True,
        reconnection_attempts=0,      # infinite retries
        reconnection_delay=5,
        reconnection_delay_max=10,
        logger=False,
        engineio_logger=False,
    )

    @_sio.event
    def connect():
        db_log("INFO", f"[WS] Connected to ERP at {ws_url}")
        # Authenticate as biometric agent using the same token format
        _sio.emit("authenticate-biometricagent", token)

    @_sio.event
    def disconnect():
        db_log("WARN", "[WS] Disconnected from ERP — will reconnect automatically")

    @_sio.event
    def connect_error(data):
        db_log("ERROR", f"[WS] Connection error: {data}")

    @_sio.on("sync")
    def on_sync(data=None):
        _handle_sync(data)

    @_sio.on("enroll_user")
    def on_enroll_user(data):
        _handle_enroll_user(data)

    @_sio.on("complete_enrollment")
    def on_complete_enrollment(data):
        _handle_complete_enrollment(data)

    try:
        db_log("INFO", f"[WS] Connecting to ERP at {ws_url}")
        _sio.connect(ws_url, transports=["websocket"])
        _sio.wait()  # blocks thread until disconnect + all retries exhausted
    except Exception as e:
        db_log("ERROR", f"[WS] Socket client error: {e}")


def start_socket_client(cfg: dict):
    """Start the Socket.IO client in a daemon thread. Call from main.py."""
    global _client_thread
    _client_thread = threading.Thread(
        target=_start_client, args=(cfg,), daemon=True, name="ws-client")
    _client_thread.start()
    log.info("WebSocket client thread started")


def stop_socket_client():
    global _sio
    if _sio:
        try:
            _sio.disconnect()
        except Exception:
            pass


def emit_to_erp(event: str, data: dict):
    """Utility — emit an event to ERP from anywhere in the codebase."""
    if _sio and _sio.connected:
        _sio.emit(event, data)
    else:
        log.warning(f"[WS] emit_to_erp: not connected, dropping event '{event}'")