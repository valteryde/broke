"""
Settings Views and API Endpoints
Handles user preferences, webhooks, and workspace configuration
"""

from utils.security import secureroute
from utils.models import (
    User, Project, ProjectPart, Label, UserSettings, 
    Webhook, WebhookDelivery, GitHubIntegration, APIToken,
    database
)
from flask import redirect, render_template, request
from utils.app import app
from peewee import DoesNotExist
import json
import hashlib
import time
import secrets
import re


# ============ Settings Page Routes ============

@secureroute('/settings')
def settings_view(user: User):
    """Default settings view - redirects to profile"""
    return redirect('/settings/profile')


@secureroute('/settings/<section>')
def settings_section_view(user: User, section: str):
    """Render settings page for a specific section"""
    
    # Map sections to their display titles
    section_titles = {
        'profile': 'Profile',
        'preferences': 'Preferences',
        'notifications': 'Notifications',
        'security': 'Security',
        'general': 'General',
        'projects': 'Projects',
        'team': 'Team Members',
        'labels': 'Labels',
        'api': 'API & Tokens',
        'webhooks': 'Webhooks',
        'sentry': 'Sentry Integration',
        'billing': 'Billing',
        'danger': 'Danger Zone'
    }
    
    section_title = section_titles.get(section, section.title())
    
    # Get or create user settings
    user_settings = get_or_create_user_settings(user)
    
    # Base context
    context = {
        'user': user,
        'page': 'settings',
        'section': section,
        'section_title': section_title,
        'user_settings': user_settings
    }
    
    # Section-specific data
    if section == 'profile':
        context['user_settings'] = user_settings
        
    elif section == 'preferences':
        context['user_settings'] = user_settings
        
    elif section == 'notifications':
        context['user_settings'] = user_settings
        
    elif section == 'projects':
        context['projects'] = list(Project.select().order_by(Project.name))
        
    elif section == 'team':
        context['team_members'] = list(User.select().order_by(User.username))
        
    elif section == 'labels':
        context['labels'] = list(Label.select().order_by(Label.name))
        
    elif section == 'api':
        context['api_tokens'] = list(APIToken.select().where(
            APIToken.user == user.username
        ).order_by(APIToken.created_at.desc()))
        
    elif section == 'webhooks':
        context['projects'] = list(Project.select().order_by(Project.name))
        context['base_url'] = request.host_url.rstrip('/')
        context['webhook_secret'] = get_webhook_secret(user)
        context['github_webhook_secret'] = get_github_webhook_secret(user)
        
        # GitHub integration status
        github_integration = get_github_integration(user)
        context['github_connected'] = github_integration is not None and github_integration.connected
        context['github_repo'] = github_integration.repository if github_integration else None
        context['github_settings'] = github_integration
        
        # Outgoing webhooks
        context['outgoing_webhooks'] = list(Webhook.select().where(
            Webhook.user == user.username
        ).order_by(Webhook.created_at.desc()))
        
        # Recent webhook activity
        context['webhook_activity'] = get_recent_webhook_activity(user, limit=10)
        
    elif section == 'sentry':
        context['project_parts'] = list(ProjectPart.select())
        context['base_url'] = request.host_url.rstrip('/')
    
    return render_template('settings.jinja2', **context)


# ============ Settings API Endpoints ============

@app.route('/api/settings/profile', methods=['POST'])
def api_update_profile():
    """Update user profile settings"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    
    # Update email if provided
    if 'email' in data:
        email = data['email'].strip()
        if email and email != user.email:
            # Check if email is already taken
            try:
                existing = User.get(User.email == email)
                if existing.username != user.username:
                    return json.dumps({'error': 'Email already in use'}), 400
            except DoesNotExist:
                pass
            user.email = email
            user.save()
    
    # Update display name in settings
    if 'display_name' in data:
        settings = get_or_create_user_settings(user)
        settings.display_name = data['display_name'].strip()
        settings.save()
    
    return json.dumps({'success': True}), 200


@app.route('/api/settings/preferences', methods=['POST'])
def api_update_preferences():
    """Update user preferences"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    settings = get_or_create_user_settings(user)
    
    # Update preferences
    if 'theme' in data:
        settings.theme = data['theme']
    if 'compact_mode' in data:
        settings.compact_mode = 1 if data['compact_mode'] else 0
    if 'animations' in data:
        settings.animations = 1 if data['animations'] else 0
    if 'home_page' in data:
        settings.home_page = data['home_page']
    if 'ticket_view' in data:
        settings.default_ticket_view = data['ticket_view']
    if 'timezone' in data:
        settings.timezone = data['timezone']
    if 'date_format' in data:
        settings.date_format = data['date_format']
    
    settings.save()
    
    return json.dumps({'success': True}), 200


@app.route('/api/settings/notifications', methods=['POST'])
def api_update_notifications():
    """Update notification settings"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    settings = get_or_create_user_settings(user)
    
    # Update notification preferences (stored as JSON)
    notification_prefs = json.loads(settings.notification_settings or '{}')
    notification_prefs.update(data)
    settings.notification_settings = json.dumps(notification_prefs)
    settings.save()
    
    return json.dumps({'success': True}), 200


@app.route('/api/settings/security/password', methods=['POST'])
def api_change_password():
    """Change user password"""
    from utils.security import get_current_user
    import pyargon2
    
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    
    # Verify current password
    if pyargon2.hash(current_password, user.salt) != user.password_hash:
        return json.dumps({'error': 'Current password is incorrect'}), 400
    
    # Validate new password
    if len(new_password) < 8:
        return json.dumps({'error': 'Password must be at least 8 characters'}), 400
    
    # Update password
    user.password_hash = pyargon2.hash(new_password, user.salt)
    user.save()
    
    return json.dumps({'success': True, 'message': 'Password updated successfully'}), 200


# ============ Webhook API Endpoints ============

@app.route('/api/settings/webhooks/regenerate-secret', methods=['POST'])
def api_regenerate_webhook_secret():
    """Regenerate webhook secret"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    secret_type = data.get('type', 'github')
    
    settings = get_or_create_user_settings(user)
    
    if secret_type == 'github':
        settings.github_webhook_secret = secrets.token_hex(16)
    else:
        settings.webhook_secret = secrets.token_hex(16)
    
    settings.save()
    
    return json.dumps({'success': True}), 200


@app.route('/api/settings/webhooks/github/mappings', methods=['POST'])
def api_save_github_mappings():
    """Save GitHub repository to project mappings"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    mappings = data.get('mappings', [])
    
    for mapping in mappings:
        project_id = mapping.get('project_id')
        github_repo = mapping.get('github_repo', '').strip()
        
        try:
            project = Project.get(Project.id == project_id)
            # Store in GitHubIntegration or Project model
            integration, created = GitHubIntegration.get_or_create(
                project=project_id,
                defaults={
                    'user': user.username,
                    'repository': github_repo,
                    'connected': bool(github_repo)
                }
            )
            if not created:
                integration.repository = github_repo
                integration.connected = bool(github_repo)
                integration.save()
        except DoesNotExist:
            continue
    
    return json.dumps({'success': True}), 200


@app.route('/api/settings/webhooks/github/disconnect', methods=['POST'])
def api_disconnect_github():
    """Disconnect GitHub integration"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    # Delete all GitHub integrations for this user
    GitHubIntegration.delete().where(GitHubIntegration.user == user.username).execute()
    
    return json.dumps({'success': True}), 200


@app.route('/api/settings/webhooks/github/settings', methods=['POST'])
def api_update_github_settings():
    """Update GitHub webhook event settings"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    settings = get_or_create_user_settings(user)
    
    github_settings = json.loads(settings.github_settings or '{}')
    github_settings.update({
        'create_tickets_from_issues': data.get('issues', True),
        'link_commits': data.get('commits', True),
        'sync_comments': data.get('comments', False),
        'close_on_merge': data.get('close_on_merge', True)
    })
    settings.github_settings = json.dumps(github_settings)
    settings.save()
    
    return json.dumps({'success': True}), 200


@app.route('/api/settings/webhooks/outgoing', methods=['POST'])
def api_create_outgoing_webhook():
    """Create a new outgoing webhook"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    url = data.get('url', '').strip()
    events = data.get('events', [])
    secret = data.get('secret', '')
    
    if not url:
        return json.dumps({'error': 'URL is required'}), 400
    
    # Validate URL format
    if not url.startswith(('http://', 'https://')):
        return json.dumps({'error': 'Invalid URL format'}), 400
    
    webhook = Webhook.create(
        user=user.username,
        url=url,
        events=json.dumps(events),
        secret=secret,
        active=True,
        created_at=int(time.time())
    )
    
    return json.dumps({'success': True, 'webhook_id': webhook.id}), 200


@app.route('/api/settings/webhooks/<int:webhook_id>', methods=['DELETE'])
def api_delete_webhook(webhook_id: int):
    """Delete an outgoing webhook"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    try:
        webhook = Webhook.get(
            (Webhook.id == webhook_id) & 
            (Webhook.user == user.username)
        )
        webhook.delete_instance()
        return json.dumps({'success': True}), 200
    except DoesNotExist:
        return json.dumps({'error': 'Webhook not found'}), 404


@app.route('/api/settings/webhooks/<int:webhook_id>/test', methods=['POST'])
def api_test_webhook(webhook_id: int):
    """Send a test event to a webhook"""
    from utils.security import get_current_user
    import urllib.request
    import urllib.error
    
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    try:
        webhook = Webhook.get(
            (Webhook.id == webhook_id) & 
            (Webhook.user == user.username)
        )
    except DoesNotExist:
        return json.dumps({'error': 'Webhook not found'}), 404
    
    # Send test payload
    test_payload = {
        'event': 'test',
        'timestamp': int(time.time()),
        'message': 'This is a test webhook from Broke'
    }
    
    try:
        req = urllib.request.Request(
            webhook.url,
            data=json.dumps(test_payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'X-Broke-Event': 'test',
                'X-Broke-Delivery': secrets.token_hex(8)
            }
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            status_code = response.getcode()
            
        # Log successful delivery
        log_webhook_delivery(webhook, 'test', status_code, 'success')
        
        return json.dumps({'success': True, 'status_code': status_code}), 200
        
    except urllib.error.HTTPError as e:
        log_webhook_delivery(webhook, 'test', e.code, 'error')
        return json.dumps({'success': False, 'status_code': e.code}), 200
        
    except Exception as e:
        log_webhook_delivery(webhook, 'test', 0, 'error')
        return json.dumps({'error': str(e)}), 500


# ============ API Token Endpoints ============

@app.route('/api/settings/tokens', methods=['POST'])
def api_create_token():
    """Create a new API token"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    name = data.get('name', 'API Token').strip()
    
    # Generate secure token
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    api_token = APIToken.create(
        user=user.username,
        name=name,
        token_hash=token_hash,
        token_preview=token[:8] + '...',
        created_at=int(time.time())
    )
    
    # Return the full token only once
    return json.dumps({
        'success': True,
        'token': token,
        'token_id': api_token.id,
        'message': 'Save this token now - you won\'t be able to see it again!'
    }), 200


@app.route('/api/settings/tokens/<int:token_id>', methods=['DELETE'])
def api_delete_token(token_id: int):
    """Delete an API token"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    try:
        token = APIToken.get(
            (APIToken.id == token_id) & 
            (APIToken.user == user.username)
        )
        token.delete_instance()
        return json.dumps({'success': True}), 200
    except DoesNotExist:
        return json.dumps({'error': 'Token not found'}), 404


# ============ Project & Label Management ============

@app.route('/api/settings/projects', methods=['POST'])
def api_create_project():
    """Create a new project"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    name = data.get('name', '').strip()
    
    if not name:
        return json.dumps({'error': 'Project name is required'}), 400
    
    # Generate project ID from name
    project_id = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    
    # Check if project exists
    try:
        Project.get(Project.id == project_id)
        return json.dumps({'error': 'Project already exists'}), 400
    except DoesNotExist:
        pass
    
    project = Project.create(
        id=project_id,
        name=name,
        icon=data.get('icon', 'ph ph-folder'),
        color=data.get('color', '#106ecc')
    )
    
    return json.dumps({
        'success': True,
        'project_id': project.id,
        'name': project.name
    }), 200


@app.route('/api/settings/projects/<project_id>', methods=['DELETE'])
def api_delete_project(project_id: str):
    """Delete a project"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user or not user.admin:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    try:
        project = Project.get(Project.id == project_id)
        # Delete associated parts first
        ProjectPart.delete().where(ProjectPart.project == project_id).execute()
        project.delete_instance()
        return json.dumps({'success': True}), 200
    except DoesNotExist:
        return json.dumps({'error': 'Project not found'}), 404


@app.route('/api/settings/labels', methods=['POST'])
def api_create_label():
    """Create a new label"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    name = data.get('name', '').strip()
    color = data.get('color', '#888888')
    
    if not name:
        return json.dumps({'error': 'Label name is required'}), 400
    
    try:
        Label.get(Label.name == name)
        return json.dumps({'error': 'Label already exists'}), 400
    except DoesNotExist:
        pass
    
    label = Label.create(name=name, color=color)
    
    return json.dumps({
        'success': True,
        'name': label.name,
        'color': label.color
    }), 200


@app.route('/api/settings/labels/<label_name>', methods=['DELETE'])
def api_delete_label(label_name: str):
    """Delete a label"""
    from utils.security import get_current_user
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    try:
        label = Label.get(Label.name == label_name)
        label.delete_instance()
        return json.dumps({'success': True}), 200
    except DoesNotExist:
        return json.dumps({'error': 'Label not found'}), 404


# ============ Danger Zone ============

@app.route('/api/settings/danger/delete-account', methods=['POST'])
def api_delete_account():
    """Delete user account"""
    from utils.security import get_current_user
    import pyargon2
    
    user = get_current_user()
    if not user:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    password = data.get('password', '')
    
    # Verify password
    if pyargon2.hash(password, user.salt) != user.password_hash:
        return json.dumps({'error': 'Incorrect password'}), 400
    
    # Delete user data
    UserSettings.delete().where(UserSettings.user == user.username).execute()
    Webhook.delete().where(Webhook.user == user.username).execute()
    APIToken.delete().where(APIToken.user == user.username).execute()
    
    # Finally delete user
    user.delete_instance()
    
    return json.dumps({'success': True}), 200


@app.route('/api/settings/danger/clear-data', methods=['POST'])
def api_clear_all_data():
    """Clear all user data"""
    from utils.security import get_current_user
    from utils.models import Ticket, Comment, ErrorGroup, ErrorOccurrence
    import pyargon2
    
    user = get_current_user()
    if not user or not user.admin:
        return json.dumps({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    password = data.get('password', '')
    
    # Verify password
    if pyargon2.hash(password, user.salt) != user.password_hash:
        return json.dumps({'error': 'Incorrect password'}), 400
    
    # Clear data (keeping users and projects)
    Comment.delete().execute()
    Ticket.delete().execute()
    ErrorOccurrence.delete().execute()
    ErrorGroup.delete().execute()
    
    return json.dumps({'success': True}), 200


# ============ GitHub Webhook Handler ============

@app.route('/api/webhooks/github/<secret>', methods=['POST'])
def github_webhook(secret: str):
    """
    Handle incoming GitHub webhook events.
    
    Supported events:
    - issues: Create tickets from GitHub issues
    - push: Link commits to tickets
    - pull_request: Track PRs and close tickets on merge
    - issue_comment: Sync comments to tickets
    """
    from utils.models import Ticket, Comment
    
    # Get the event type from headers
    event_type = request.headers.get('X-GitHub-Event', 'ping')
    delivery_id = request.headers.get('X-GitHub-Delivery', '')
    
    # Handle ping event (GitHub sends this when webhook is created)
    if event_type == 'ping':
        return json.dumps({'message': 'Pong! Webhook configured successfully.'}), 200
    
    try:
        payload = request.get_json()
    except:
        return json.dumps({'error': 'Invalid JSON payload'}), 400
    
    if not payload:
        return json.dumps({'error': 'Empty payload'}), 400
    
    # Get repository info
    repo = payload.get('repository', {})
    repo_full_name = repo.get('full_name', '')
    
    # Find the project mapped to this repository
    project = None
    try:
        integration = GitHubIntegration.get(GitHubIntegration.repository == repo_full_name)
        project = Project.get(Project.id == integration.project)
    except DoesNotExist:
        # Try to find by name
        try:
            repo_name = repo.get('name', '')
            project = Project.get(Project.name == repo_name)
        except DoesNotExist:
            project = Project.select().first()
    
    if not project:
        return json.dumps({'error': 'No matching project found'}), 404
    
    response_data = {'event': event_type, 'delivery_id': delivery_id}
    
    # Handle different event types
    if event_type == 'issues':
        response_data.update(handle_github_issue_event(payload, project))
    elif event_type == 'push':
        response_data.update(handle_github_push_event(payload, project))
    elif event_type == 'pull_request':
        response_data.update(handle_github_pr_event(payload, project))
    elif event_type == 'issue_comment':
        response_data.update(handle_github_comment_event(payload, project))
    else:
        response_data['message'] = f'Event type "{event_type}" received but not processed'
    
    return json.dumps(response_data), 200


# ============ Helper Functions ============

def get_or_create_user_settings(user: User) -> 'UserSettings':
    """Get or create user settings"""
    try:
        return UserSettings.get(UserSettings.user == user.username)
    except DoesNotExist:
        return UserSettings.create(
            user=user.username,
            theme='light',
            compact_mode=0,
            animations=1,
            home_page='news',
            default_ticket_view='list',
            timezone='UTC',
            date_format='dmy',
            notification_settings='{}',
            github_settings='{}',
            webhook_secret=secrets.token_hex(16),
            github_webhook_secret=secrets.token_hex(16)
        )


def get_webhook_secret(user: User) -> str:
    """Get or generate webhook secret for user"""
    settings = get_or_create_user_settings(user)
    return settings.webhook_secret or user.username


def get_github_webhook_secret(user: User) -> str:
    """Get or generate GitHub webhook secret for user"""
    settings = get_or_create_user_settings(user)
    return settings.github_webhook_secret or hashlib.sha256(f"github-{user.username}".encode()).hexdigest()[:24]


def get_github_integration(user: User):
    """Get GitHub integration for user"""
    try:
        return GitHubIntegration.select().where(
            GitHubIntegration.user == user.username
        ).first()
    except:
        return None


def get_recent_webhook_activity(user: User, limit: int = 10) -> list:
    """Get recent webhook delivery activity"""
    try:
        deliveries = WebhookDelivery.select().join(Webhook).where(
            Webhook.user == user.username
        ).order_by(WebhookDelivery.timestamp.desc()).limit(limit)
        
        return [{
            'event': d.event,
            'status': d.status,
            'response_code': d.response_code,
            'time': time_ago(d.timestamp)
        } for d in deliveries]
    except:
        return []


def log_webhook_delivery(webhook: 'Webhook', event: str, response_code: int, status: str):
    """Log a webhook delivery attempt"""
    try:
        WebhookDelivery.create(
            webhook=webhook,
            event=event,
            response_code=response_code,
            status=status,
            timestamp=int(time.time())
        )
    except:
        pass


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


# ============ GitHub Event Handlers ============

def handle_github_issue_event(payload: dict, project: Project) -> dict:
    """Handle GitHub issue events - create/update tickets."""
    from utils.models import Ticket
    
    action = payload.get('action', '')
    issue = payload.get('issue', {})
    
    issue_number = issue.get('number')
    issue_title = issue.get('title', 'Untitled Issue')
    issue_body = issue.get('body', '') or ''
    issue_url = issue.get('html_url', '')
    
    if action == 'opened':
        try:
            existing = Ticket.get(Ticket.title.contains(f"[GitHub #{issue_number}]"))
            return {'action': 'skipped', 'reason': 'Ticket already exists'}
        except DoesNotExist:
            pass
        
        ticket = Ticket.create(
            id=f"{project.id}-gh-{issue_number}",
            project=project.id,
            title=f"[GitHub #{issue_number}] {issue_title}",
            description=f"{issue_body}\n\n---\n*Created from GitHub issue: {issue_url}*",
            status='todo',
            priority='medium',
            created_at=int(time.time())
        )
        
        return {'action': 'created', 'ticket_id': str(ticket.id), 'issue_number': issue_number}
    
    elif action == 'closed':
        try:
            ticket = Ticket.get(Ticket.title.contains(f"[GitHub #{issue_number}]"))
            ticket.status = 'closed'
            ticket.save()
            return {'action': 'closed', 'ticket_id': str(ticket.id)}
        except DoesNotExist:
            return {'action': 'skipped', 'reason': 'No matching ticket found'}
    
    elif action == 'reopened':
        try:
            ticket = Ticket.get(Ticket.title.contains(f"[GitHub #{issue_number}]"))
            ticket.status = 'todo'
            ticket.save()
            return {'action': 'reopened', 'ticket_id': str(ticket.id)}
        except DoesNotExist:
            return {'action': 'skipped', 'reason': 'No matching ticket found'}
    
    return {'action': action, 'processed': False}


def handle_github_push_event(payload: dict, project: Project) -> dict:
    """Handle GitHub push events - link commits to tickets."""
    from utils.models import Ticket, Comment, User
    
    commits = payload.get('commits', [])
    linked_tickets = []
    
    ticket_pattern = re.compile(r'(?:fix|fixes|fixed|close|closes|closed|resolve|resolves|resolved|refs?)\s*#(\d+)', re.IGNORECASE)
    
    for commit in commits:
        message = commit.get('message', '')
        commit_sha = commit.get('id', '')[:8]
        commit_url = commit.get('url', '')
        author = commit.get('author', {}).get('name', 'Unknown')
        
        matches = ticket_pattern.findall(message)
        
        for ticket_id_str in matches:
            try:
                ticket_id = int(ticket_id_str)
                ticket = Ticket.get(Ticket.id == ticket_id)
                
                Comment.create(
                    ticket=ticket.id,
                    user=User.select().first(),
                    body=f"🔗 Commit [{commit_sha}]({commit_url}) by {author}\n\n> {message.split(chr(10))[0]}",
                    created_at=int(time.time())
                )
                
                if re.search(r'(?:fix|fixes|fixed|close|closes|closed)\s*#' + ticket_id_str, message, re.IGNORECASE):
                    ticket.status = 'closed'
                    ticket.save()
                
                linked_tickets.append({'ticket_id': ticket_id, 'commit': commit_sha})
            except (DoesNotExist, ValueError):
                continue
    
    return {'action': 'push', 'commits_processed': len(commits), 'linked_tickets': linked_tickets}


def handle_github_pr_event(payload: dict, project: Project) -> dict:
    """Handle GitHub pull request events."""
    from utils.models import Ticket, Comment, User
    
    action = payload.get('action', '')
    pr = payload.get('pull_request', {})
    
    pr_number = pr.get('number')
    pr_title = pr.get('title', '')
    pr_body = pr.get('body', '') or ''
    pr_url = pr.get('html_url', '')
    merged = pr.get('merged', False)
    
    ticket_pattern = re.compile(r'(?:fix|fixes|fixed|close|closes|closed|resolve|resolves|resolved|refs?)\s*#(\d+)', re.IGNORECASE)
    
    if action == 'closed' and merged:
        all_text = f"{pr_title} {pr_body}"
        matches = ticket_pattern.findall(all_text)
        closed_tickets = []
        
        for ticket_id_str in matches:
            try:
                ticket_id = int(ticket_id_str)
                ticket = Ticket.get(Ticket.id == ticket_id)
                ticket.status = 'closed'
                ticket.save()
                
                Comment.create(
                    ticket=ticket.id,
                    user=User.select().first(),
                    body=f"✅ Closed via PR #{pr_number}: [{pr_title}]({pr_url})",
                    created_at=int(time.time())
                )
                
                closed_tickets.append(ticket_id)
            except (DoesNotExist, ValueError):
                continue
        
        return {'action': 'merged', 'pr_number': pr_number, 'closed_tickets': closed_tickets}
    
    return {'action': action, 'pr_number': pr_number}


def handle_github_comment_event(payload: dict, project: Project) -> dict:
    """Handle GitHub issue comment events."""
    from utils.models import Ticket, Comment, User
    
    action = payload.get('action', '')
    issue = payload.get('issue', {})
    comment = payload.get('comment', {})
    
    if action != 'created':
        return {'action': action, 'processed': False}
    
    issue_number = issue.get('number')
    comment_body = comment.get('body', '')
    comment_user = comment.get('user', {}).get('login', 'github')
    comment_url = comment.get('html_url', '')
    
    try:
        ticket = Ticket.get(Ticket.title.contains(f"[GitHub #{issue_number}]"))
        
        Comment.create(
            ticket=ticket.id,
            user=User.select().first(),
            body=f"💬 **{comment_user}** commented on GitHub:\n\n{comment_body}\n\n[View on GitHub]({comment_url})",
            created_at=int(time.time())
        )
        
        return {'action': 'comment_synced', 'ticket_id': str(ticket.id)}
    except DoesNotExist:
        return {'action': 'skipped', 'reason': 'No matching ticket found'}
