"""Workspace instance logo (public branding asset on disk)."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Optional

from .path import data_path

INSTANCE_LOGO_PREFIX = "instance-logo"
ALLOWED_INSTANCE_LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_INSTANCE_LOGO_SIZE_BYTES = 5 * 1024 * 1024
DEFAULT_INSTANCE_LOGO_STATIC = "images/logov2_wo_bg.png"


def branding_dir() -> Path:
    d = data_path("branding")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _allowed_suffixes() -> tuple[str, ...]:
    return tuple({v.lower() for v in ALLOWED_INSTANCE_LOGO_TYPES.values()})


def resolve_instance_logo_path() -> Optional[Path]:
    """Return path to custom logo if present (at most one file: instance-logo.<ext>)."""
    d = data_path("branding")
    if not d.is_dir():
        return None
    for ext in _allowed_suffixes():
        p = d / f"{INSTANCE_LOGO_PREFIX}{ext}"
        if p.is_file():
            return p
    return None


def instance_logo_mtime() -> Optional[int]:
    p = resolve_instance_logo_path()
    if not p:
        return None
    return int(p.stat().st_mtime)


def has_custom_instance_logo() -> bool:
    return resolve_instance_logo_path() is not None


def instance_logo_mimetype(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    return "application/octet-stream"


def _logo_magic_is_valid(content_type: str, header_bytes: bytes) -> bool:
    if content_type == "image/png":
        return header_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return header_bytes.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return len(header_bytes) >= 12 and header_bytes.startswith(b"RIFF") and header_bytes[8:12] == b"WEBP"
    return False


def clear_instance_logo_files() -> None:
    d = data_path("branding")
    if not d.is_dir():
        return
    for ext in _allowed_suffixes():
        p = d / f"{INSTANCE_LOGO_PREFIX}{ext}"
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass


def save_instance_logo_from_upload(file) -> tuple[bool, str, int]:
    """
    Validate and persist multipart upload field to branding dir.
    Returns (ok, message, http_status).
    """
    content_type = (getattr(file, "content_type", None) or "").lower()
    extension = ALLOWED_INSTANCE_LOGO_TYPES.get(content_type)
    if not extension:
        return False, "Unsupported image format", 400

    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > MAX_INSTANCE_LOGO_SIZE_BYTES:
        return False, "Logo file too large (max 5 MB)", 413

    header = file.stream.read(12)
    file.stream.seek(0)
    if not _logo_magic_is_valid(content_type, header):
        return False, "Invalid image file", 400

    out_dir = branding_dir()
    clear_instance_logo_files()
    dest = out_dir / f"{INSTANCE_LOGO_PREFIX}{extension}"
    file.save(str(dest))
    return True, "", 200
