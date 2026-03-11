from app.utils.app import create_app
from app.utils.models import Ticket, UserTicketJoin, User
from peewee import prefetch

app = create_app()
with app.app_context():
    q = Ticket.select().limit(2)
    utj = UserTicketJoin.select()
    u = User.select()
    res = prefetch(q, utj, u)
    for t in res:
        print(t, list(t.userticketjoin_set))
