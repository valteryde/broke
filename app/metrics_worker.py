"""Dedicated process: compact the metrics hot tier into Parquet and apply retention.

Only needed when ``METRICS_COMPACTION_IN_PROCESS=0`` turns off the in-app thread, e.g.
for installs large enough to want the work isolated from request handling.
"""

from __future__ import annotations

import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [broke-metrics] %(levelname)s %(message)s",
)
logger = logging.getLogger("broke.metrics_worker")


def main() -> int:
    from app.utils.features import FEATURE_METRICS, is_feature_enabled
    from app.utils.metrics_store import compact_interval_seconds
    from app.utils.metrics_worker import run_locked_maintenance

    if not is_feature_enabled(FEATURE_METRICS):
        logger.info("Metrics feature disabled (BROKE_DISABLED_FEATURES); exiting")
        return 0

    logger.info("Starting metrics worker (interval=%ss)", compact_interval_seconds())
    while True:
        if not is_feature_enabled(FEATURE_METRICS):
            logger.info("Metrics feature disabled; exiting")
            return 0
        try:
            result = run_locked_maintenance()
            if result and result["rows_compacted"]:
                logger.info(
                    "Compacted %s rows into %s file(s)",
                    result["rows_compacted"],
                    result["files_written"],
                )
        except Exception:
            logger.exception("Metrics maintenance sweep failed")
        time.sleep(compact_interval_seconds())


if __name__ == "__main__":
    sys.exit(main())
