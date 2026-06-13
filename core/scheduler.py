"""
core/scheduler.py
Background thread that runs auto-sync on a configurable interval.

sync_mode behaviour:
  - "manual"   → scheduler never auto-triggers (user clicks Sync in UI)
  - "timely"   → existing behaviour, ticks every interval_seconds
  - "realtime" → ERP triggers sync via WebSocket; scheduler still ticks
                 as a fallback every interval_seconds in case WS drops
"""
import logging
import threading

log = logging.getLogger("zk_agent")
_scheduler_thread = None
_stop_event = threading.Event()


def _loop(cfg: dict):
    from core.erp_sync import full_sync
    from core.database import db_log

    interval = cfg["sync"].get("interval_seconds", 60)

    while not _stop_event.is_set():
        # Re-read config on each tick (so UI changes take effect without restart)
        try:
            from core.config import get_full_config
            live_cfg = get_full_config()
        except Exception:
            live_cfg = cfg

        sync_mode = live_cfg["sync"].get("sync_mode", "timely")

        if sync_mode in ("timely", "realtime"):
            db_log("INFO", f"[SCHEDULER] Auto-sync triggered (mode={sync_mode})")
            try:
                result = full_sync(live_cfg)
                db_log("INFO",
                    f"[SCHEDULER] Sync done — sdk_pulled={result['sdk_pulled']} "
                    f"pushed={result['pushed']} errors={len(result['errors'])}")
            except Exception as e:
                db_log("ERROR", f"[SCHEDULER] Sync error: {e}")

        _stop_event.wait(interval)


def start_scheduler(cfg: dict):
    global _scheduler_thread
    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_loop, args=(cfg,), daemon=True, name="scheduler")
    _scheduler_thread.start()
    log.info("Scheduler started")


def stop_scheduler():
    _stop_event.set()