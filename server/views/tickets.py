
from utils.security import secureroute
from utils.models import User
from flask import render_template

@secureroute('/tickets')
def tickets_view(user: User):
    return render_template('tickets.jinja2', 
        user=user
    )



