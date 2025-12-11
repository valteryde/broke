
from werkzeug import Response
from ..utils.models import GlobalSetting, Project, Ticket, TicketUpdateMessage, User, UserTicketJoin, Label
from flask import Blueprint, render_template, request, redirect, flash, send_file, jsonify
import uuid
import time
import json
import secrets
from ..utils.path import data_path
from ..utils.app import get_limiter
from typing import Literal

anon_bp = Blueprint('anon', __name__)

def get_anon_settings():
    try:
        setting = GlobalSetting.get(GlobalSetting.key == 'anonymous_settings')
        return json.loads(setting.value)
    except:
        return {'enabled': False, 'message': 'Welcome! Please submit your ticket below.', 'projects': []}

@anon_bp.route('/anon')
def anon_index() -> tuple[str, Literal[403]] | tuple[str, Literal[500]] | Response | str:
    settings = get_anon_settings()
    
    if not settings.get('enabled'):
        return render_template('error_message.jinja2', error_code=403, error_message="Anonymous tickets are currently disabled."), 403

    allowed_projects = settings.get('projects', [])
    if not allowed_projects:
        return render_template('error_message.jinja2', error_code=500, error_message="No projects configured for anonymous submission."), 500
    projects = Project.select().where(Project.id.in_(settings.get('projects', [])))
    
    # If only one project, redirect directly to it
    if len(projects) == 1:
        return redirect(f'/anon/{projects[0].id}')
        
    return render_template('anon_wizard.jinja2', 
        step='project_selection',
        projects=projects,
        welcome_message=settings.get('message', '')
    )

@anon_bp.route('/anon/<project_id>')
def anon_wizard(project_id: str):
    settings = get_anon_settings()
    if not settings.get('enabled'):
        return render_template('error_message.jinja2', error_code=403, error_message="Anonymous tickets are currently disabled."), 403

    allowed_projects = settings.get('projects', [])
    if project_id not in allowed_projects:
         return render_template('error_message.jinja2', error_code=404, error_message="Project not found or not allowed."), 404
    project = Project.get_or_none(Project.id == project_id)
    if not project:
        return render_template('error_message.jinja2', error_code=404, error_message="Project not found."), 404
    
    labels = Label.select()

    return render_template('anon_wizard.jinja2', 
        step='form',
        project=project,
        labels=labels,
        welcome_message=settings.get('message', '')
    )

@anon_bp.route('/api/anon/submit', methods=['POST'])
@get_limiter().limit("5 per hour")
def api_anon_submit():
    settings = get_anon_settings()
    if not settings.get('enabled'):
        return jsonify({'error': 'Anonymous tickets disabled'}), 403

    data = request.get_json()
    project_id = data.get('project')
    
    if project_id not in settings.get('projects', []):
        return jsonify({'error': 'Invalid project'}), 400

    # Generate ticket ID (reusing logic from tickets.py or duplicating for cleanliness)
    # Ideally should be a shared utility, but for now copying logic is safer than refactoring widely
    existing_tickets = Ticket.select().where(Ticket.project == project_id)
    max_num = 0
    for t in existing_tickets:
        parts = t.id.split('-')
        if len(parts) >= 2:
            try:
                num = int(parts[-1])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    ticket_id = f"{project_id}-{max_num + 1}"
    
    # Generate Secret
    secret = secrets.token_urlsafe(16)
    
    ticket = Ticket.create(
        id=ticket_id,
        title=data.get('title', 'Anonymous Ticket'),
        description=data.get('description', ''),
        status='backlog', # Default status
        priority=data.get('priority', 'medium'),
        project=project_id,
        created_at=int(time.time()),
        anonymous_secret=secret
    )
    
    TicketUpdateMessage.create(
        ticket=ticket_id,
        title='Anonymous Ticket Created',
        icon='ph ph-mask-happy',
        message='A user submitted this ticket anonymously.',
        created_at=int(time.time())
    )

    return jsonify({'success': True, 'secret': secret, 'ticket_id': ticket_id}), 201

@anon_bp.route('/anon/track/<secret>')
def anon_track(secret: str):
    ticket = Ticket.get_or_none(Ticket.anonymous_secret == secret)
    if not ticket:
        return render_template('error_message.jinja2', error_code=404, error_message="Tracking link invalid or expired."), 404
        
    project = Project.get_or_none(Project.id == ticket.project)
    
    # Populate minimal data
    ticket.updates = list(TicketUpdateMessage.select().where(TicketUpdateMessage.ticket == ticket.id).order_by(TicketUpdateMessage.id))
    
    return render_template('anon_track.jinja2', 
        ticket=ticket,
        project=project
    )
