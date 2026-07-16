"""
Server-side feature toggles from environment.

Use BROKE_DISABLED_FEATURES=comma,separated,feature ids to turn off functionality
that must not be reachable via the UI or API (e.g. updater).
"""

import os

_ENV_KEY = "BROKE_DISABLED_FEATURES"

# Known ids (documented); unknown tokens are ignored until wired up elsewhere.
FEATURE_UPDATER = "updater"


def get_disabled_features() -> frozenset[str]:
    raw = (os.environ.get(_ENV_KEY) or "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def is_feature_enabled(name: str) -> bool:
    return name.strip().lower() not in get_disabled_features()
