import json

from .models import GlobalSetting

PUBLIC_SITE_SETTINGS_KEY = "public_site_settings"
DEFAULT_PUBLIC_SITE_SETTINGS = {"show_public_home": False}


def get_public_site_settings() -> dict:
    merged = dict(DEFAULT_PUBLIC_SITE_SETTINGS)
    try:
        row = GlobalSetting.get(GlobalSetting.key == PUBLIC_SITE_SETTINGS_KEY)
        stored = json.loads(row.value)
        if isinstance(stored, dict):
            merged.update(stored)
    except (GlobalSetting.DoesNotExist, json.JSONDecodeError, TypeError):
        pass
    return merged


def show_public_home() -> bool:
    return bool(get_public_site_settings().get("show_public_home"))


def set_show_public_home(enabled: bool) -> dict:
    payload = dict(DEFAULT_PUBLIC_SITE_SETTINGS)
    payload.update(get_public_site_settings())
    payload["show_public_home"] = bool(enabled)
    value = json.dumps(payload)
    row = GlobalSetting.get_or_none(GlobalSetting.key == PUBLIC_SITE_SETTINGS_KEY)
    if row:
        row.value = value
        row.save()
    else:
        GlobalSetting.create(key=PUBLIC_SITE_SETTINGS_KEY, value=value)
    return payload
