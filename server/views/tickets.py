
from utils.security import secureroute
from utils.models import User, Ticket
from flask import render_template

@secureroute('/tickets')
def tickets_view(user: User):
    return render_template('tickets.jinja2', 
        user=user
    )

@secureroute('/tickets/<ticket_id>')
def ticket_detail_view(user: User, ticket_id: str):
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)

    return render_template('ticket.jinja2', 
        user=user,
        ticket = ticket
    )
