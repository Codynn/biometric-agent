"""
core/scheduler.py
Background thread that runs auto-sync on a configurable interval.
"""
import logging
import threading
import time

log = logging.getLogger("zk_agent")
_scheduler_thread = None
_stop_event = threading.Event()


def _loop(cfg: dict):
    from core.erp_sync import full_sync
    from core.database import db_log

    interval = cfg["sync"].get("interval_seconds", 60)

    while not _stop_event.is_set():
        # Re-read config on each tick (so UI changes take effect)
        import json
        from pathlib import Path
        try:
            with open(Path(__file__).parent.parent / "config.json") as f:
                live_cfg = json.load(f)
        except Exception:
            live_cfg = cfg

        if live_cfg["sync"].get("auto_sync", False):
            db_log("INFO", "[SCHEDULER] Auto-sync triggered")
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
