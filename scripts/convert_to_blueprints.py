#!/usr/bin/env python3
"""
Script to convert all view routes to use blueprints with the @secureroute decorator
"""

import re


def add_secureroute_decorator(file_path, blueprint_name):
    """Add @secureroute decorator above @blueprint.route decorators that have a user parameter"""

    with open(file_path, "r") as f:
        content = f.read()

    # Pattern to match blueprint route decorators followed by function definitions with user parameter
    # We want to add @secureroute between the @bp.route and the def
    pattern = rf"(@{blueprint_name}\.route\([^\)]+\))\n(def \w+\(user: User)"

    def replace_func(match):
        route_decorator = match.group(1)
        func_def = match.group(2)
        return f"{route_decorator}\n@secureroute\n{func_def}"

    # Apply the replacement
    new_content = re.sub(pattern, replace_func, content)

    # Write back
    with open(file_path, "w") as f:
        f.write(new_content)

    print(f"Updated {file_path}")


# Update all view files
files_to_update = [
    ("app/views/tickets.py", "tickets_bp"),
    ("app/views/bug.py", "bug_bp"),
    ("app/views/settings.py", "settings_bp"),
    ("app/views/news.py", "news_bp"),
    ("app/views/webhooks.py", "webhooks_bp"),
]

for file_path, bp_name in files_to_update:
    try:
        add_secureroute_decorator(file_path, bp_name)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
