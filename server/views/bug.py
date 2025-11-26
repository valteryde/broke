
from utils.security import secureroute
from utils.models import User, Ticket
from flask import render_template

@secureroute('/news')
def news_view(user: User):
    return render_template('news.jinja2', 
        user=user,
        page = 'news'
    )
