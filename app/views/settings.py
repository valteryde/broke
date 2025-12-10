"""
Settings Views and API Endpoints
Handles user preferences, webhooks, and workspace configuration
"""

import os
from ..utils.security import secureroute
from ..utils.models import *
from flask import redirect, render_template, request, flash, Blueprint
from ..utils.reltime import time_ago
from peewee import DoesNotExist
import json
import hashlib
import time
import secrets
import re

# Create blueprint
settings_bp = Blueprint('settings', __name__)


# ============ Settings Page Routes ============

@settings_bp.route('/settings')
@secureroute
def settings_view(user: User):
    """Default settings view - redirects to profile"""
    return redirect('/settings/profile')


@settings_bp.route('/settings/<section>')
@secureroute
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
        'trash': 'Trash',
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
        context['webhook_secret'] = get_webhook_secret()
        context['github_webhook_secret'] = get_github_webhook_secret()
        
        # Outgoing webhooks
        context['outgoing_webhooks'] = list(Webhook.select().where(
            Webhook.user == user.username
        ).order_by(Webhook.created_at.desc()))
        
        # Recent webhook activity
        context['webhook_activity'] = get_recent_webhook_activity(user, limit=10)
        
    elif section == 'sentry':
        context['project_parts'] = list(ProjectPart.select())
        context['base_url'] = request.host_url.rstrip('/')
        
        # Get DSN token if it exists
        try:
            dsn_token = DSNToken.get()
            context['dsn_token'] = dsn_token
        except DoesNotExist:
            context['dsn_token'] = None

    elif section == 'trash':
        # Fetch deleted tickets
        context['deleted_tickets'] = list(Ticket.select().where(Ticket.active == 0).order_by(Ticket.created_at.desc()))
    
    return render_template('settings.jinja2', **context)


# ============ Settings API Endpoints ============

@settings_bp.route('/api/settings/profile', methods=['POST'])
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


@settings_bp.route('/api/settings/preferences', methods=['POST'])
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


@settings_bp.route('/api/settings/notifications', methods=['POST'])
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


@settings_bp.route('/api/settings/security/password', methods=['POST'])
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
    if pyargon2.hash(current_password, str(user.salt)) != user.password_hash:
        return json.dumps({'error': 'Current password is incorrect'}), 400
    
    # Validate new password
    if len(new_password) < 8:
        return json.dumps({'error': 'Password must be at least 8 characters'}), 400
    
    # Update password
    user.password_hash = pyargon2.hash(new_password, str(user.salt)) # type: ignore
    user.save()
    
    return json.dumps({'success': True, 'message': 'Password updated successfully'}), 200


# ============ Webhook API Endpoints ============

@settings_bp.route('/api/settings/webhooks/regenerate-secret', methods=['POST'])
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


@settings_bp.route('/api/settings/webhooks/outgoing', methods=['POST'])
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


@settings_bp.route('/api/settings/webhooks/<int:webhook_id>', methods=['DELETE'])
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


@settings_bp.route('/api/settings/webhooks/<int:webhook_id>/test', methods=['POST'])
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


# ============ MEMBERS ============
@secureroute('/api/settings/team/invite', methods=['POST'])
def api_invite_team_member(user:User):
    """Invite a new team member by creating a create token"""

    data = request.form
    name = data.get('name', '').strip()
    is_admin = data.get('admin', 'off') == 'on'

    if not name:
        flash('Name is required to invite a team member.', 'error')
        return redirect('/settings/team')
    
    # Generate a temporary invite token
    invite_token = secrets.token_urlsafe(32)
    invite_token_hash = hashlib.sha256(invite_token.encode()).hexdigest()

    UserCreateToken.create(
        token=invite_token_hash,
        created_at=int(time.time()),
        name=name,
    )

    base_url = request.host_url.rstrip('/')

    return render_template('invite_sent.jinja2', name=name, token=invite_token, base_url=base_url, user=user, page='settings', section='team')


@settings_bp.route('/welcome/<token>', methods=['GET', 'POST'])
def welcome_new_member(token:str):
    """Welcome a new team member and allow them to set up their account"""
    from utils.security import get_current_user
    import pyargon2

    # Verify the token
    try:
        
        invite = UserCreateToken.get(UserCreateToken.token == hashlib.sha256(token.encode()).hexdigest())

    except DoesNotExist:
        flash('Invalid or expired invite token.', 'error')
        return redirect('/login')

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        email = request.form.get('email', '').strip()

        # Validate and create user account
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return redirect(request.url)

        create_user(username, password, email, )

        

        # Delete the invite token after use
        invite.delete_instance()

        flash('Account created successfully! Please log in.', 'success')
        return redirect('/news')

    return render_template('welcome_new_member.jinja2', token=token, name=invite.name)



# ============ API Token Endpoints ============

@secureroute('/api/settings/tokens', methods=['POST'])
def api_create_token(user:User):
    """Create a new API token"""
        
    # Generate secure token
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    api_token = APIToken.create(
        user=user.username,
        token_hash=token_hash,
        token_preview=token[:8],
        created_at=int(time.time())
    )
    
    # Return the full token only once
    return json.dumps({
        'success': True,
        'token': token,
        'token_id': api_token.id,
    }), 200


@secureroute('/api/settings/tokens/<int:token_id>', methods=['DELETE'])
def api_delete_token(user:User, token_id: int):
    """Delete an API token"""
    
    try:
        token = APIToken.get(
            (APIToken.id == token_id) & 
            (APIToken.user == user.username)
        )
        token.delete_instance()
        return json.dumps({'success': True}), 200
    except DoesNotExist:
        return json.dumps({'error': 'Token not found'}), 404


# ============ DSN Token Endpoints ============

@secureroute('/api/settings/dsn-token', methods=['POST'])
def api_create_dsn_token(user:User):
    """Create or replace the DSN token - only one can exist"""
    
    # Delete any existing DSN token
    DSNToken.delete().execute()
    
    # Generate secure token
    token = secrets.token_urlsafe(32)
    
    dsn_token = DSNToken.create(
        token=token,
        created_at=int(time.time())
    )
    
    return json.dumps({
        'success': True,
        'token': token,
        'token_id': dsn_token.id,
    }), 200


@secureroute('/api/settings/dsn-token', methods=['DELETE'])
def api_revoke_dsn_token(user:User):
    """Revoke the DSN token"""
    
    count = DSNToken.delete().execute()
    
    if count > 0:
        return json.dumps({'success': True}), 200
    else:
        return json.dumps({'error': 'No DSN token exists'}), 404


@secureroute('/api/settings/projects', methods=['POST'])
def api_create_project(user:User):
    """Create a new project"""
    
    data = request.form
    name = data.get('name', '').strip()
    
    if not name:
        return json.dumps({'error': 'Project name is required'}), 400
    
    # Generate project ID from name
    project_id = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:3].upper()
    
    # Check if project exists
    try:
        Project.get(Project.id == project_id)
        
        # TODO: Handle ID conflicts better (e.g., append numbers)
        flash('Project ID already exists. Please choose a different name.', 'error')
    
        return redirect('/settings/projects')
    except DoesNotExist:
        pass
    
    project = Project.create(
        id=project_id,
        name=name,
        icon=data.get('icon', 'ph ph-folder'),
        color=data.get('color', '#106ecc')
    )
    
    flash(f'Project "{name}" created successfully.', 'success')

    return redirect('/settings/projects')


@secureroute('/api/settings/projects/delete/<project_id>', methods=['GET'])
def api_delete_project(user:User, project_id: str):
    """Delete a project"""
    
    try:
        project = Project.get(Project.id == project_id)
        # Delete associated parts first
        ProjectPart.delete().where(ProjectPart.project == project_id).execute()
        project.delete_instance()
        
        flash(f'Project "{project.name}" deleted successfully.', 'success')

        return redirect('/settings/projects')
    except DoesNotExist:

        flash('Project not found.', 'error')

        return redirect('/settings/projects')


@secureroute('/api/settings/projects/update/<project_id>', methods=['GET', 'POST'])
def api_update_project(user:User, project_id: str):
    """Update project details"""
    
    try:
        project = Project.get(Project.id == project_id)
    except DoesNotExist:
        flash('Project not found.', 'error')
        return redirect('/settings/projects')
    
    data = request.form
        
    project.name = data.get('name', project.name)
    project.icon = data.get('icon', project.icon)
    project.color = data.get('color', project.color)
    project.save()
    
    flash(f'Project "{project.id}" updated successfully.', 'success')
    return redirect('/settings/projects')
    
@secureroute('/api/settings/labels', methods=['POST'])
def api_create_label(user:User):
    """Create a new label"""
    
    data = request.form
    name = data.get('name', '').strip()
    color = data.get('color', "#0075E3")
    
    if not name:
        flash('Label name is required.', 'error')
        return redirect('/settings/labels')
    
    try:
        Label.get(Label.name == name)
        flash('Label already exists.', 'error')
        return redirect('/settings/labels')
    except DoesNotExist:
        pass
    
    label = Label.create(name=name, color=color)
    
    flash(f'Label "{name}" created successfully.', 'success')
    return redirect('/settings/labels')


@secureroute('/api/settings/labels/delete/<label_name>')
def api_delete_label(user:User, label_name: str):
    """Delete a label"""
    
    try:
        label = Label.get(Label.name == label_name)
        label.delete_instance()
        flash(f'Label "{label_name}" deleted successfully.', 'success')
    except DoesNotExist:
        flash('Label not found.', 'error')
    return redirect('/settings/labels')


# ============ Danger Zone ============

@settings_bp.route('/api/settings/danger/delete-account', methods=['POST'])
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


def get_secret_from_txt_file(fpath:str) -> str: 
    
    # Get or create settings
    if not os.path.exists(data_path(fpath)):
        with open(data_path(fpath), 'w') as f:
            f.write(secrets.token_hex(16))

    with open(data_path(fpath), 'r') as f:
        secret = f.read().strip()

    return secret



def get_webhook_secret() -> str:
    """Get or generate webhook secret"""
    return get_secret_from_txt_file('webhook_secret.txt')


def get_github_webhook_secret() -> str:
    """Get or generate webhook secret"""
    return get_secret_from_txt_file('github_webhook_secret.txt')


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


