# Relative Time Utility

import time


def time_ago(timestamp: int) -> str:
    """Convert Unix timestamp to human-readable time ago string"""
    now = int(time.time())
    diff = now - timestamp

    if diff < 60:
        return "just now"
    elif diff < 3600:
        minutes = diff // 60
        return f"{minutes}m ago"
    elif diff < 86400:
        hours = diff // 3600
        return f"{hours}h ago"
    elif diff < 604800:
        days = diff // 86400
        return f"{days}d ago"
    else:
        weeks = diff // 604800
        return f"{weeks}w ago"
