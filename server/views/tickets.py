
from utils.security import secureroute
from utils.models import TicketLabelJoin, User, Ticket, Project, Comment, TicketUpdateMessage, UserTicketJoin, Label
from flask import redirect, render_template, request, jsonify, send_file
from utils.app import app
import time
import os
import base64
import uuid
import re
from utils.path import data_path, path


def populateTickets(tickets: list[Ticket]) -> None:
    """
    Populates the tickets page with tickets from the database.

    Adds labels, comments, and update messages to each ticket.
    
    Parameters:
        tickets (list): List of Ticket objects to populate.
    """

    for ticket in tickets:
        # Fetch and attach labels
        ticket.labels = [Label.get_or_none(Label.name == tlj.label) for tlj in TicketLabelJoin.select().where(TicketLabelJoin.ticket == ticket.id)] # type: ignore

        # Fetch and attach comments
        ticket.comments = [comment for comment in Comment.select().where(Comment.ticket == ticket.id).order_by(Comment.id)] # type: ignore
        
        # Fetch and attach update messages
        ticket.updates = [update for update in TicketUpdateMessage.select().where(TicketUpdateMessage.ticket == ticket.id).order_by(TicketUpdateMessage.id)] # type: ignore

        # Add assigned users
        ticket.assignees = [User.get_or_none(User.username == utj.user) for utj in UserTicketJoin.select().where(UserTicketJoin.ticket == ticket.id)] # type: ignore


@secureroute('/tickets')
def tickets_view(user: User):
    tickets = list(Ticket.select())
    populateTickets(tickets)

    available_users = User.select().order_by(User.username)
    available_labels = Label.select().order_by(Label.name)

    return render_template('tickets.jinja2', 
        user=user,
        page = 'tickets',
        tickets = tickets,
        project = None,
        projects = Project.select().distinct().order_by(Project.name),
        group = request.args.get('group'),
        available_users = available_users,
        available_labels = available_labels
    )

@secureroute('/tickets/<project_id>')
def project_tickets_view(user: User, project_id: str):
    project = Project.get_or_none(Project.id == project_id)
    tickets = list(Ticket.select().where(Ticket.project == project_id))
    populateTickets(tickets)

    available_users = User.select().order_by(User.username)
    available_labels = Label.select().order_by(Label.name)

    return render_template('tickets.jinja2', 
        user=user,
        project = project,
        tickets = tickets,
        page = 'tickets',
        projects = Project.select().distinct().order_by(Project.name),
        group = request.args.get('group'),
        available_users = available_users,
        available_labels = available_labels
    )

@secureroute('/tickets/<project_id>/<ticket_id>')
def ticket_detail_view(user: User, project_id: str, ticket_id: str):
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)

    if ticket is None:
        return redirect(f'/tickets/{project_id}')

    populateTickets([ticket])  # type: ignore

    available_users = User.select().order_by(User.username)
    available_labels = Label.select().order_by(Label.name)

    comments = Comment.select().where(Comment.ticket == ticket_id).order_by(Comment.id)  # type: ignore
    updates = TicketUpdateMessage.select().where(TicketUpdateMessage.ticket == ticket_id).order_by(TicketUpdateMessage.id)  # type: ignore

    return render_template('ticket.jinja2', 
        user=user,
        ticket = ticket,
        project = Project.get_or_none(Project.id == project_id),
        page = 'tickets',
        available_users = available_users,
        available_labels = available_labels,
        comments = comments,
        updates = updates,
    )


# ============ Ticket API Endpoints ============

def generate_ticket_id(project_id: str) -> str:
    """Generate a ticket ID in the format PROJ-123"""
    # Find the highest ticket number for this project
    existing_tickets = Ticket.select().where(Ticket.project == project_id)
    max_num = 0
    for ticket in existing_tickets:
        # Extract number from ID like "PROJ-123"
        parts = ticket.id.split('-')
        if len(parts) >= 2:
            try:
                num = int(parts[-1])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    
    return f"{project_id}-{max_num + 1}"


def extract_and_save_images(html_content: str) -> str:
    """
    Extract base64 images from HTML content, save them to disk, 
    and replace with URLs.
    """
    if not html_content:
        return html_content
    
    # Match base64 images in src attributes
    pattern = r'src="data:image/([^;]+);base64,([^"]+)"'
    
    def replace_image(match):
        image_type = match.group(1)
        base64_data = match.group(2)
        
        # Generate unique filename
        filename = f"{uuid.uuid4().hex}.{image_type}"
        
        # Ensure upload directory exists
        upload_dir = data_path("uploads")
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save image to disk
        filepath = os.path.join(upload_dir, filename)
        try:
            image_data = base64.b64decode(base64_data)
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            # Return URL to saved image
            return f'src="/uploads/{filename}"'
        except Exception as e:
            # If save fails, keep original
            return match.group(0)
    
    return re.sub(pattern, replace_image, html_content)


@secureroute('/api/tickets', methods=['POST'])
def create_ticket(user: User):
    """Create a new ticket"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    project_id = data.get('project')
    if not project_id:
        return jsonify({'error': 'Project is required'}), 400
    
    # Verify project exists
    project = Project.get_or_none(Project.id == project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Generate ticket ID
    ticket_id = generate_ticket_id(project_id)
    
    # Create ticket with defaults
    ticket = Ticket.create(
        id=ticket_id,
        title=data.get('title', ''),
        description=data.get('description', ''),
        status=data.get('status', 'todo'),
        priority=data.get('priority', 'medium'),
        project=project_id,
        created_at=int(time.time())
    )
    
    # Create initial activity message
    TicketUpdateMessage.create(
        ticket=ticket_id,
        title='Created',
        icon='ph ph-plus',
        message=f'{user.username} created this ticket',
        created_at=int(time.time())
    )
    
    return jsonify({
        'success': True,
        'ticket': {
            'id': ticket.id,
            'title': ticket.title,
            'project': ticket.project,
            'status': ticket.status,
            'priority': ticket.priority
        }
    }), 201


@secureroute('/api/tickets/<ticket_id>', methods=['PUT', 'PATCH'])
def update_ticket(user: User, ticket_id: str):
    """Update a ticket field"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket not found'}), 404
    
    field = data.get('field')
    value = data.get('value')
    old_value = data.get('oldValue')
    
    if not field:
        return jsonify({'error': 'Field is required'}), 400
    
    # Rate limit for update messages (10 minutes = 600 seconds)
    UPDATE_MESSAGE_COOLDOWN = 600
    
    def should_create_update_message(ticket_id: str, title: str) -> bool:
        """Check if enough time has passed since the last update message of this type"""
        last_update = (TicketUpdateMessage
            .select()
            .where(
                (TicketUpdateMessage.ticket == ticket_id) & 
                (TicketUpdateMessage.title == title)
            )
            .order_by(TicketUpdateMessage.created_at.desc())
            .first())
        
        if not last_update:
            return True
        
        return int(time.time()) - last_update.created_at >= UPDATE_MESSAGE_COOLDOWN
    
    # Handle different field types
    if field == 'title':
        ticket.title = value
        ticket.save()
        
        # Rate-limited update message
        if should_create_update_message(ticket_id, 'Title changed'):
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title='Title changed',
                icon='ph ph-pencil',
                message=f'{user.username} changed the title',
                created_at=int(time.time())
            )
        
    elif field == 'description':
        # Extract and save base64 images
        processed_description = extract_and_save_images(value)
        
        if processed_description == ticket.description:
            return jsonify({'success': True})

        ticket.description = processed_description
        ticket.save()
        
        # Rate-limited update message
        if should_create_update_message(ticket_id, 'Description updated'):
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title='Description updated',
                icon='ph ph-note-pencil',
                message=f'{user.username} updated the description',
                created_at=int(time.time())
            )
        
    elif field == 'status':
        old_status = ticket.status
        ticket.status = value
        ticket.save()
        
        TicketUpdateMessage.create(
            ticket=ticket_id,
            title='Status changed',
            icon='ph ph-arrow-right',
            message=f'{user.username} changed status from {old_status} to {value}',
            created_at=int(time.time())
        )
        
    elif field == 'priority':
        old_priority = ticket.priority
        ticket.priority = value
        ticket.save()
        
        TicketUpdateMessage.create(
            ticket=ticket_id,
            title='Priority changed',
            icon='ph ph-cell-signal-full',
            message=f'{user.username} changed priority from {old_priority} to {value}',
            created_at=int(time.time())
        )
        
    elif field == 'assignees':
        # Value should be list of user objects with id property
        # Clear existing assignments
        UserTicketJoin.delete().where(UserTicketJoin.ticket == ticket_id).execute()
        
        # Add new assignments
        assigned_usernames = []
        if value:
            for assignee in value:
                user_id = assignee.get('id') if isinstance(assignee, dict) else assignee
                UserTicketJoin.create(user=user_id, ticket=ticket_id)
                assigned_usernames.append(user_id)
        
        TicketUpdateMessage.create(
            ticket=ticket_id,
            title='Assignees changed',
            icon='ph ph-users-three',
            message=f'{user.username} updated assignees to: {", ".join(assigned_usernames) if assigned_usernames else "unassigned"}',
            created_at=int(time.time())
        )
        
    elif field == 'labels':
        # Clear existing labels
        TicketLabelJoin.delete().where(TicketLabelJoin.ticket == ticket_id).execute()
        
        # Add new labels
        label_names = []
        if value:
            for label in value:
                label_name = label.get('name') if isinstance(label, dict) else label
                TicketLabelJoin.create(ticket=ticket_id, label=label_name)
                label_names.append(label_name)
        
        TicketUpdateMessage.create(
            ticket=ticket_id,
            title='Labels changed',
            icon='ph ph-tag',
            message=f'{user.username} updated labels to: {", ".join(label_names) if label_names else "none"}',
            created_at=int(time.time())
        )
        
    else:
        return jsonify({'error': f'Unknown field: {field}'}), 400
    
    return jsonify({'success': True})


@secureroute('/api/tickets/<ticket_id>/comments', methods=['POST'])
def add_comment(user: User, ticket_id: str):
    """Add a comment to a ticket"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket not found'}), 404
    
    content = data.get('content', '')
    if not content.strip():
        return jsonify({'error': 'Comment content is required'}), 400
    
    # Extract and save any images in the comment
    processed_content = extract_and_save_images(content)
    
    comment = Comment.create(
        ticket=ticket_id,
        user=user.username,
        body=processed_content,
        created_at=int(time.time())
    )
    
    return jsonify({
        'success': True,
        'comment': {
            'id': comment.id,
            'user': user.username,
            'body': comment.body,
            'created_at': comment.created_at
        }
    }), 201


@secureroute('/api/comments/<int:comment_id>', methods=['DELETE'])
def delete_comment(user: User, comment_id: int):
    """Delete a comment"""
    comment = Comment.get_or_none(Comment.id == comment_id)
    if not comment:
        return jsonify({'error': 'Comment not found'}), 404
    
    # Only allow the comment author or admin to delete
    if comment.user.username != user.username and not user.admin:
        return jsonify({'error': 'Not authorized'}), 403
    
    comment.delete_instance()
    
    return jsonify({'success': True})


@secureroute('/api/projects', methods=['GET'])
def get_projects(user: User):
    """Get all projects for the dropdown"""
    projects = Project.select().order_by(Project.name)
    
    return jsonify({
        'projects': [{
            'id': p.id,
            'name': p.name,
            'icon': p.icon,
            'color': p.color
        } for p in projects]
    })


@secureroute('/uploads/<path:filename>', methods=['GET'])
def get_uploads(user: User, filename: str):
    """Get all uploads for the user (placeholder)"""
    
    return send_file(data_path("uploads", filename))