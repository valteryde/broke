
import sys
import os
import argparse
import re
import uuid
import base64
import requests
from utils.models import User, create_user, Project, Ticket, Label, TicketLabelJoin, UserTicketJoin, database
from utils.path import data_path


def download_linear_image(url: str, api_key: str) -> str | None:
    """Download an image from Linear and save it locally, returning the local path"""
    try:
        # Linear images require authentication
        headers = {"Authorization": api_key}
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f"    Warning: Failed to download image {url}: {response.status_code}")
            return None
        
        # Determine file extension from content-type
        content_type = response.headers.get('Content-Type', 'image/png')
        ext_map = {
            'image/png': 'png',
            'image/jpeg': 'jpg',
            'image/jpg': 'jpg',
            'image/gif': 'gif',
            'image/webp': 'webp',
            'image/svg+xml': 'svg'
        }
        ext = ext_map.get(content_type, 'png')
        
        # Generate unique filename
        filename = f"{uuid.uuid4().hex}.{ext}"
        
        # Ensure upload directory exists
        upload_dir = data_path("uploads")
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save image to disk
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(response.content)
        
        return f"/uploads/{filename}"
    except Exception as e:
        print(f"    Warning: Error downloading image {url}: {e}")
        return None


def markdown_to_html(text: str, api_key: str | None = None) -> str:
    """Convert markdown to HTML for Quill.js editor.
    If api_key is provided, Linear images will be downloaded and stored locally."""
    if not text:
        return ""
    
    html = text
    
    # Escape HTML entities first (but preserve existing HTML if any)
    # html = html.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # Code blocks (``` ... ```) - must be before inline code
    html = re.sub(
        r'```(\w*)\n(.*?)```',
        lambda m: f'<pre class="ql-syntax" spellcheck="false">{m.group(2)}</pre>',
        html,
        flags=re.DOTALL
    )
    
    # Inline code (`...`)
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
    
    # Remove any remaining backticks that weren't part of code blocks
    html = html.replace('`', '')
    
    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    
    # Bold (**text** or __text__)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'__(.+?)__', r'<strong>\1</strong>', html)
    
    # Italic (*text* or _text_) - be careful not to match already processed bold
    html = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', html)
    html = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<em>\1</em>', html)
    
    # Strikethrough (~~text~~)
    html = re.sub(r'~~(.+?)~~', r'<s>\1</s>', html)
    
    # Helper to download and replace Linear images
    def process_image_url(url: str, alt: str = "") -> str:
        print(f"    Found image: {url}")
        
        # Check if this is a Linear-hosted image
        if api_key and ('linear.app' in url or 'uploads.linear.app' in url):
            local_path = download_linear_image(url, api_key)
            if local_path:
                return f'<img src="{local_path}" alt="{alt}">'
        
        # Keep original URL for non-Linear images
        return f'<img src="{url}" alt="{alt}">'
    
    # Image file extensions
    image_extensions = r'\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)(\?[^)\s]*)?'
    
    # Images ![alt](url) - standard markdown image syntax
    def replace_md_image(match):
        alt = match.group(1)
        url = match.group(2)
        return process_image_url(url, alt)
    
    html = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_md_image, html)
    
    # Links that point to image URLs should become images, not links
    # Matches [text](url) where url ends with image extension
    def replace_image_link(match):
        alt = match.group(1)
        url = match.group(2)
        return process_image_url(url, alt)
    
    html = re.sub(rf'\[([^\]]*)\]\(([^)]+{image_extensions})\)', replace_image_link, html)
    
    # Plain image URLs (Linear sometimes uses these)
    def replace_plain_image_url(match):
        url = match.group(0)
        return process_image_url(url, "")
    
    html = re.sub(rf'https?://[^\s<>"]+{image_extensions}', replace_plain_image_url, html)
    
    # Links [text](url) - after images (won't match image URLs anymore)
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', html)
    
    # Blockquotes (> text)
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
    
    # Unordered lists (- item or * item)
    html = re.sub(r'^[\-\*] (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    
    # Ordered lists (1. item)
    html = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    
    # Wrap consecutive <li> tags in <ul>
    html = re.sub(r'((?:<li>.*?</li>\n?)+)', r'<ul>\1</ul>', html)
    
    # Horizontal rules (---, ***, ___)
    html = re.sub(r'^[\-\*_]{3,}$', r'<hr>', html, flags=re.MULTILINE)
    
    # Replace all newlines with <br>
    html = html.replace('\n', '<br>')
    
    return html


def linear_graphql_request(api_key: str, query: str, variables: dict | None = None) -> dict:
    """Make a GraphQL request to Linear API"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key
    }
    
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    response = requests.post(
        "https://api.linear.app/graphql",
        headers=headers,
        json=payload
    )
    
    if response.status_code != 200:
        raise Exception(f"Linear API error: {response.status_code} - {response.text}")
    
    data = response.json()
    if "errors" in data:
        raise Exception(f"GraphQL errors: {data['errors']}")
    
    return data["data"]


def import_from_linear(api_key: str):
    """Import teams, issues, and labels from Linear"""
    
    # Ensure database is set up
    database.connect()
    database.create_tables([Project, Ticket, Label, TicketLabelJoin, UserTicketJoin], safe=True)
    database.close()

    print("Connecting to Linear API...")
    
    # First, get the viewer to verify the API key works
    viewer_data = linear_graphql_request(api_key, """
        query {
            viewer {
                id
                name
                email
            }
        }
    """)
    print(f"Authenticated as: {viewer_data['viewer']['name']} ({viewer_data['viewer']['email']})")
    
    # Get all teams (these become projects in Broke)
    print("\nFetching teams...")
    teams_data = linear_graphql_request(api_key, """
        query {
            teams {
                nodes {
                    id
                    name
                    key
                }
            }
        }
    """)
    
    teams = teams_data["teams"]["nodes"]
    print(f"Found {len(teams)} teams")
    
    # Get all labels
    print("\nFetching labels...")
    labels_data = linear_graphql_request(api_key, """
        query {
            issueLabels {
                nodes {
                    id
                    name
                    color
                }
            }
        }
    """)
    
    labels = labels_data["issueLabels"]["nodes"]
    print(f"Found {len(labels)} labels")
    
    # Create labels in database
    label_map = {}  # Linear label ID -> Broke label name
    for label in labels:
        label_name = label["name"]
        label_map[label["id"]] = label_name
        try:
            Label.get_or_create(
                name=label_name,
                defaults={"color": label["color"]}
            )
            print(f"  Created label: {label_name}")
        except Exception as e:
            print(f"  Label {label_name} already exists or error: {e}")
    
    # Get workflow states for status mapping
    print("\nFetching workflow states...")
    states_data = linear_graphql_request(api_key, """
        query {
            workflowStates {
                nodes {
                    id
                    name
                    type
                }
            }
        }
    """)
    
    states = {s["id"]: s for s in states_data["workflowStates"]["nodes"]}
    
    # Map Linear state types to Broke statuses
    state_type_map = {
        "triage": "backlog",
        "backlog": "backlog",
        "unstarted": "todo",
        "started": "in-progress",
        "completed": "done",
        "canceled": "closed"
    }
    
    # Map Linear priority (0-4, where 0 is no priority, 1 is urgent, 4 is low)
    priority_map = {
        0: "none",
        1: "urgent",
        2: "high",
        3: "medium",
        4: "low"
    }
    
    # Process each team
    total_issues = 0
    for team in teams:
        print(f"\nProcessing team: {team['name']} ({team['key']})")
        
        # Create project for this team
        try:
            project, created = Project.get_or_create(
                id=team["key"],
                defaults={
                    "name": team["name"],
                    "icon": "ph ph-folder",
                    "color": "blue"
                }
            )
            if created:
                print(f"  Created project: {team['name']}")
            else:
                print(f"  Project {team['name']} already exists")
        except Exception as e:
            print(f"  Error creating project: {e}")
            continue
        
        # Fetch issues for this team with pagination
        has_next_page = True
        cursor = None
        team_issue_count = 0
        
        while has_next_page:
            variables = {"teamId": team["id"]}
            if cursor:
                variables["after"] = cursor
            
            issues_data = linear_graphql_request(api_key, """
                query($teamId: String!, $after: String) {
                    team(id: $teamId) {
                        issues(first: 50, after: $after, includeArchived: true) {
                            pageInfo {
                                hasNextPage
                                endCursor
                            }
                            nodes {
                                id
                                identifier
                                title
                                description
                                priority
                                createdAt
                                state {
                                    id
                                    type
                                }
                                assignee {
                                    name
                                    email
                                }
                                labels {
                                    nodes {
                                        id
                                    }
                                }
                            }
                        }
                    }
                }
            """, variables)
            
            issues = issues_data["team"]["issues"]["nodes"]
            page_info = issues_data["team"]["issues"]["pageInfo"]
            
            for issue in issues:
                # Map status
                state_type = issue["state"]["type"] if issue["state"] else "backlog"
                status = state_type_map.get(state_type, "backlog")
                
                # Map priority
                priority = priority_map.get(issue["priority"] or 0, "none")
                
                # Convert markdown description to HTML for Quill.js (downloads images)
                description_html = markdown_to_html(issue["description"] or "", api_key)
                
                # Create ticket
                ticket_id = issue["identifier"]  # e.g., "LIN-123"
                
                try:
                    ticket, created = Ticket.get_or_create(
                        id=ticket_id,
                        defaults={
                            "title": issue["title"],
                            "description": description_html,
                            "status": status,
                            "priority": priority,
                            "project": team["key"],
                            "created_at": int(__import__("datetime").datetime.fromisoformat(
                                issue["createdAt"].replace("Z", "+00:00")
                            ).timestamp())
                        }
                    )
                    
                    if created:
                        team_issue_count += 1
                        
                        # Add labels
                        for label_node in issue.get("labels", {}).get("nodes", []):
                            label_name = label_map.get(label_node["id"])
                            if label_name:
                                try:
                                    TicketLabelJoin.get_or_create(
                                        ticket=ticket_id,
                                        label=label_name
                                    )
                                except:
                                    pass
                        
                        # Add assignee if exists and user exists in system
                        if issue.get("assignee"):
                            assignee_name = issue["assignee"]["name"]
                            # Try to find user by username (simplified)
                            try:
                                user = User.get(User.username == assignee_name.lower().replace(" ", ""))
                                UserTicketJoin.get_or_create(
                                    user=user.username,
                                    ticket=ticket_id
                                )
                            except:
                                pass  # User doesn't exist in Broke
                                
                except Exception as e:
                    print(f"    Error creating ticket {ticket_id}: {e}")
            
            has_next_page = page_info["hasNextPage"]
            cursor = page_info["endCursor"]
        
        print(f"  Imported {team_issue_count} issues")
        total_issues += team_issue_count
    
    print(f"\n✓ Import complete! Imported {total_issues} issues from {len(teams)} teams.")


def cmd_create_user(args):
    """Create a new user"""
    user = create_user(args.username, args.password, email=args.email, admin=args.admin)
    print(f"User '{user.username}' created.")


def cmd_import_linear(args):
    """Import from Linear"""
    import_from_linear(args.api_key)


def main():
    parser = argparse.ArgumentParser(
        prog='broke',
        description='Broke CLI - Issue tracking and error monitoring'
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # create-user command
    user_parser = subparsers.add_parser('create-user', help='Create a new user')
    user_parser.add_argument('username', help='Username for the new user')
    user_parser.add_argument('password', help='Password for the new user')
    user_parser.add_argument('email', help='Email address for the new user')
    user_parser.add_argument('--admin', type=int, choices=[0, 1], default=0, 
                            help='Admin flag (0 or 1, default: 0)')
    user_parser.set_defaults(func=cmd_create_user)
    
    # import command with subcommands
    import_parser = subparsers.add_parser('import', help='Import data from external services')
    import_subparsers = import_parser.add_subparsers(dest='source', help='Import source')
    
    # import linear
    linear_parser = import_subparsers.add_parser('linear', help='Import from Linear')
    linear_parser.add_argument('api_key', help='Linear API key (get from https://linear.app/settings/account/security)')
    linear_parser.set_defaults(func=cmd_import_linear)
    
    # Parse arguments
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    if args.command == 'import' and args.source is None:
        import_parser.print_help()
        return
    
    # Execute the command
    if hasattr(args, 'func'):
        args.func(args)


if __name__ == '__main__':
    main()
