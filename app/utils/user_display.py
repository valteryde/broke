"""Resolve human-facing labels for users (display_name from UserSettings, else username)."""


def effective_display_name(username: str, raw: str | None) -> str:
    """Return trimmed display_name when non-empty; otherwise username."""
    label = (raw or "").strip()
    return label if label else (username or "")


def build_display_name_map_for(usernames: list[str]) -> dict[str, str]:
    """Map username -> label for the given set only (two queries max)."""
    unique = sorted({u for u in usernames if u})
    if not unique:
        return {}

    from .models import UserSettings

    rows = UserSettings.select(UserSettings.user, UserSettings.display_name).where(
        UserSettings.user.in_(unique)
    )
    raw_by_user = {r.user: r.display_name for r in rows}

    return {u: effective_display_name(u, raw_by_user.get(u)) for u in unique}


def build_all_display_name_map() -> dict[str, str]:
    """Map every User.username -> label (one UserSettings query + one User query)."""
    from .models import User, UserSettings

    settings_rows = UserSettings.select(UserSettings.user, UserSettings.display_name)
    raw_by_user = {r.user: r.display_name for r in settings_rows}

    result: dict[str, str] = {}
    for u in User.select(User.username):
        un = u.username
        result[un] = effective_display_name(un, raw_by_user.get(un))
    return result
