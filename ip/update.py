"""Download and atomically replace the DB-IP City Lite MMDB."""

from __future__ import annotations

import gzip
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger("broke-ip")

DOWNLOAD_URL = "https://download.db-ip.com/free/dbip-city-lite-{stamp}.mmdb.gz"
TIMEOUT_SECONDS = 120


def month_stamp(now: float | None = None) -> str:
    dt = datetime.fromtimestamp(now if now is not None else time.time(), tz=timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}"


def download_url(stamp: str | None = None) -> str:
    return DOWNLOAD_URL.format(stamp=stamp or month_stamp())


def mmdb_path(data_dir: Path, stamp: str | None = None) -> Path:
    return Path(data_dir) / f"dbip-city-lite-{stamp or month_stamp()}.mmdb"


def latest_mmdb(data_dir: Path) -> Path | None:
    """Newest City Lite file in data_dir, or None."""
    files = sorted(Path(data_dir).glob("dbip-city-lite-*.mmdb"))
    return files[-1] if files else None


def download_month(data_dir: Path, stamp: str | None = None, *, timeout: int = TIMEOUT_SECONDS) -> Path:
    """Fetch the gzipped MMDB for ``stamp`` and write it next to older months.

    Download to a temp file, gunzip, then ``os.replace`` onto the final path so a
    reader never sees a half-written database.
    """
    stamp = stamp or month_stamp()
    dest = mmdb_path(data_dir, stamp)
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("City Lite %s already on disk", stamp)
        return dest

    url = download_url(stamp)
    logger.info("Downloading City Lite %s", stamp)
    response = requests.get(url, timeout=timeout, stream=True)
    response.raise_for_status()

    data_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="dbip-", suffix=".mmdb.tmp", dir=str(data_dir))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with gzip.GzipFile(fileobj=response.raw) as gz, tmp_path.open("wb") as out:
            while True:
                chunk = gz.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp_path, dest)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise

    logger.info("City Lite %s ready (%s bytes)", stamp, dest.stat().st_size)
    return dest
