
from utils.security import secureroute
from utils.models import TicketLabelJoin, User, Ticket, Project, Comment, TicketUpdateMessage, UserTicketJoin, Label
from flask import render_template

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

    return render_template('tickets.jinja2', 
        user=user,
        page = 'tickets',
        tickets = tickets,
        project = None,
        projects = Project.select().distinct().order_by(Project.name)
    )

@secureroute('/tickets/<project_id>')
def project_tickets_view(user: User, project_id: str):
    project = Project.get_or_none(Project.id == project_id)
    tickets = list(Ticket.select().where(Ticket.project == project_id))
    populateTickets(tickets)

    return render_template('tickets.jinja2', 
        user=user,
        project = project,
        tickets = tickets,
        page = 'tickets',
        projects = Project.select().distinct().order_by(Project.name)
    )

@secureroute('/tickets/<project_id>/<ticket_id>')
def ticket_detail_view(user: User, project_id: str, ticket_id: str):
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)

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
