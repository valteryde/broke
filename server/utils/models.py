
from peewee import Model, CharField, IntegerField, SqliteDatabase
from .path import path

database = SqliteDatabase(path('..', 'data', 'app.db'))

class BaseModel(Model):
    class Meta:
        database = database

class User(BaseModel):
    username = CharField(primary_key=True)
    password_hash = CharField()
    salt = CharField()
    email = CharField(unique=True)


class Ticket(BaseModel):
    id = CharField(primary_key=True)

    title = CharField()
    description = CharField()

    body = CharField()

    status = CharField()
    priority = CharField()


class UserTicketJoin(BaseModel):
    user = CharField()
    ticket = CharField()

    class Meta: 
        indexes = (
            (('user', 'ticket'), True),
        )


class Comment(BaseModel):
    ticket = CharField()
    user = CharField()
    body = CharField()

    class Meta:
        indexes = (
            (('ticket', 'user'), False),
        )


class TicketUpdateMessage(BaseModel):
    ticket = CharField()
    
    title = CharField()
    icon = CharField()
    message = CharField()

    class Meta:
        indexes = (
            (('ticket', 'title'), False),
        )



MODELS = [
    User,
    Ticket,
    UserTicketJoin,
]

def initialize_db():
    database.connect()
    database.create_tables(MODELS, safe=True)
    database.close()


def setup_test_data():
    # Function to setup test data in the database
    import pyargon2
    salt = "randomsalt"
    try:
        User.create(username='user', password_hash=pyargon2.hash('code', salt), salt=salt, email='user@test.com')
    except:
        pass  # User already exists


    try:
        Ticket.create(
            id='DK-42', 
            title='Sample Ticket',
            description='This is a sample ticket.', 
            body='Detailed body of the ticket.', 
            status='open', 
            priority="high"
        )
    except Exception as e:
        print(e)
        pass  # Ticket already exists