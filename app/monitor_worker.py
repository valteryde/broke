"""Dedicated process: poll HTTP(S) monitors and emit MONITOR_DOWN / MONITOR_UP."""

from __future__ import annotations

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [broke-monitor] %(levelname)s %(message)s",
)
logger = logging.getLogger("broke.monitor_worker")


def main() -> int:
    from app.utils.features import FEATURE_MONITORS, is_feature_enabled
    from app.utils.models import initialize_db
    from app.utils.monitors import run_due_checks
    from app.utils.notifications import initialize_notification_engine

    if not is_feature_enabled(FEATURE_MONITORS):
        logger.info("Monitors feature disabled (BROKE_DISABLED_FEATURES); exiting")
        return 0

    initialize_db()
    initialize_notification_engine()

    try:
        poll = int(os.environ.get("MONITOR_POLL_SECONDS", "10"))
    except ValueError:
        poll = 10
    poll = max(5, min(60, poll))

    logger.info("Starting monitor worker (poll=%ss)", poll)
    while True:
        if not is_feature_enabled(FEATURE_MONITORS):
            logger.info("Monitors feature disabled; exiting")
            return 0
        try:
            from app.utils.models import database

            with database.connection_context():
                n = run_due_checks(emit=True)
            if n:
                logger.info("Checked %s monitor(s)", n)
        except Exception:
            logger.exception("Monitor sweep failed")
        time.sleep(poll)


if __name__ == "__main__":
    sys.exit(main())
