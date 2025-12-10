#!/usr/bin/env python3
"""
Fix remaining @secureroute decorators that still have route paths
Convert them to use @blueprint.route + @secureroute pattern
"""

import re

def fix_secureroute_with_paths(file_path, blueprint_name):
    """Convert @secureroute('/path') to @blueprint.route('/path') + @secureroute"""
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Pattern to match @secureroute with paths and optional methods
    # Match: @secureroute('/path') or @secureroute('/path', methods=['POST'])
    # followed by function definition with user parameter
    pattern = r"@secureroute\('([^']+)'(?:,\s*methods=(\[[^\]]+\]))?\)\ndef (\w+)\(user: User"
    
    def replace_func(match):
        path = match.group(1)
        methods = match.group(2)
        func_name = match.group(3)
        
        if methods:
            route_line = f"@{blueprint_name}.route('{path}', methods={methods})"
        else:
            route_line = f"@{blueprint_name}.route('{path}')"
        
        return f"{route_line}\n@secureroute\ndef {func_name}(user: User"
    
    # Apply the replacement
    new_content = re.sub(pattern, replace_func, content)
    
    # Write back
    with open(file_path, 'w') as f:
        f.write(new_content)
    
    print(f"Fixed @secureroute paths in {file_path}")


# Update all view files
files_to_fix = [
    ('app/views/bug.py', 'bug_bp'),
    ('app/views/settings.py', 'settings_bp'),
    ('app/views/news.py', 'news_bp'),
]

for file_path, bp_name in files_to_fix:
    try:
        fix_secureroute_with_paths(file_path, bp_name)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
