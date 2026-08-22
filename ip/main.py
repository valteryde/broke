"""
Broke IP sidecar

Holds DB-IP City Lite and answers IP → country/region/city. Intended to run on the
internal compose network (no host port) or as a single shared SaaS instance.

Endpoints:
    GET /status        — health, loaded dataset month
    GET /lookup?ip=    — JSON {country, region, city}; looks up the query IP, never the caller
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.serving import WSGIRequestHandler

from geo import PlaceCache, Reader, extract_place, is_private_ip
from update import download_month, latest_mmdb, month_stamp, mmdb_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("broke-ip")

PORT = int(os.environ.get("PORT", "9998"))
DATA_DIR = Path(os.environ.get("IP_DATA_DIR", "/data"))
SERVICE_TOKEN = (os.environ.get("IP_SERVICE_TOKEN") or "").strip()
CHECK_INTERVAL_SECONDS = int(os.environ.get("IP_CHECK_INTERVAL_SECONDS", str(24 * 3600)))

app = Flask(__name__)
reader = Reader()
cache = PlaceCache()
_state_lock = threading.Lock()
_loaded_stamp: str | None = None
_last_error: str | None = None


class _NoQueryLogHandler(WSGIRequestHandler):
    """Access logs must not include the looked-up IP from ``/lookup?ip=``."""

    def log_request(self, code="-", size="-"):
        path = (self.path or "-").split("?", 1)[0]
        try:
            self.log("info", '"%s %s %s" %s %s', self.command, path, self.request_version, code, size)
        except Exception:
            pass


def _authorized() -> bool:
    if not SERVICE_TOKEN:
        return True
    header = (request.headers.get("Authorization") or "").strip()
    if header.lower().startswith("bearer "):
        offered = header[7:].strip()
    else:
        offered = ""
    if not offered:
        return False
    return hmac.compare_digest(offered, SERVICE_TOKEN)


def _load(path: Path) -> None:
    global _loaded_stamp, _last_error
    reader.open(str(path))
    cache.clear()
    name = path.name
    stamp = None
    if name.startswith("dbip-city-lite-") and name.endswith(".mmdb"):
        stamp = name[len("dbip-city-lite-") : -len(".mmdb")]
    _loaded_stamp = stamp
    _last_error = None
    logger.info("Loaded City Lite from %s", path)


def ensure_database(*, now: float | None = None) -> None:
    """Download this month's file if missing, then open the newest MMDB on disk."""
    global _last_error
    stamp = month_stamp(now)
    try:
        download_month(DATA_DIR, stamp)
    except Exception as exc:
        logger.warning("Could not download City Lite %s: %s", stamp, exc)
        _last_error = str(exc)

    path = mmdb_path(DATA_DIR, stamp)
    if not path.exists():
        path = latest_mmdb(DATA_DIR)
    if path is None or not path.exists():
        logger.error("No City Lite MMDB available under %s", DATA_DIR)
        return

    with _state_lock:
        if reader.path == str(path) and reader.loaded:
            return
        try:
            _load(path)
        except Exception:
            logger.exception("Failed to open %s", path)


def _refresh_loop() -> None:
    while True:
        time.sleep(max(60, CHECK_INTERVAL_SECONDS))
        try:
            ensure_database()
        except Exception:
            logger.exception("Periodic City Lite refresh failed")


@app.route("/status", methods=["GET"])
def status():
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return jsonify(
        {
            "ok": reader.loaded,
            "dataset": _loaded_stamp,
            "path": reader.path,
            "node_count": reader.metadata_count,
            "error": _last_error,
        }
    )


@app.route("/lookup", methods=["GET"])
def lookup():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    ip = (request.args.get("ip") or "").strip()
    if is_private_ip(ip):
        return jsonify({"country": None, "region": None, "city": None})

    cached = cache.get(ip)
    if cached is not None:
        country, region, city = cached
        return jsonify({"country": country, "region": region, "city": city})

    if not reader.loaded:
        return jsonify({"country": None, "region": None, "city": None})

    record = reader.get(ip)
    place = extract_place(record)
    cache.put(ip, place)
    country, region, city = place
    return jsonify({"country": country, "region": region, "city": city})


if __name__ == "__main__":
    logger.info("IP sidecar starting on port %s (data=%s)", PORT, DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ensure_database()
    thread = threading.Thread(target=_refresh_loop, daemon=True, name="ip-refresh")
    thread.start()
    app.run(host="0.0.0.0", port=PORT, request_handler=_NoQueryLogHandler)
