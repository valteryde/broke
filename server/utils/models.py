
from datetime import datetime
from peewee import Model, CharField, IntegerField, SqliteDatabase, DateTimeField, ForeignKeyField
from .path import path
import time


database = SqliteDatabase(path('..', 'data', 'app.db'))

class BaseModel(Model):
    class Meta:
        database = database

class User(BaseModel):
    username = CharField(primary_key=True)
    password_hash = CharField()
    salt = CharField()
    email = CharField(unique=True)
    admin = IntegerField(default=0)


class Project(BaseModel):
    id = CharField(primary_key=True)
    name = CharField()
    icon = CharField() # classes for icons (like ph ph-* or fa fa-*)
    color = CharField() # i do not know if i will use this


class Ticket(BaseModel):
    id = CharField(primary_key=True)

    title = CharField()
    description = CharField()

    body = CharField()

    status = CharField()
    priority = CharField()

    project = CharField()

    created_at = IntegerField(default=lambda: int(time.time()))


class UserTicketJoin(BaseModel):
    user = CharField()
    ticket = CharField()

    class Meta: # type: ignore
        indexes = (
            (('user', 'ticket'), True),
        )


class Comment(BaseModel):
    ticket = CharField()
    user = ForeignKeyField(User, backref='comments')
    body = CharField()
    created_at = IntegerField(default=lambda: int(time.time()))

    class Meta: # type: ignore
        indexes = (
            (('ticket', 'user'), False),
        )


class TicketUpdateMessage(BaseModel):
    ticket = CharField()
    
    title = CharField()
    icon = CharField()
    message = CharField()
    created_at = IntegerField(default=lambda: int(time.time()))

    class Meta: # type: ignore
        indexes = (
            (('ticket', 'title'), False),
        )


class Label(BaseModel):
    name = CharField(primary_key=True)
    color = CharField()


class TicketLabelJoin(BaseModel):
    ticket = CharField()
    label = CharField()

    class Meta: # type: ignore
        indexes = (
            (('ticket', 'label'), True),
        )


MODELS = [
    User,
    Ticket,
    UserTicketJoin,
    Project,
    Comment,
    TicketUpdateMessage,
    Label,
    TicketLabelJoin,
]

def initialize_db():
    database.connect()
    database.create_tables(MODELS, safe=True)
    database.close()


def setup_test_data():
    # Function to setup test data in the database
    import pyargon2
    from faker import Faker
    import random

    random_time = lambda: int(time.time() - random.randint(0, 31536000))

    fake = Faker()

    # Delete existing data
    database.connect()
    for model in MODELS:
        model.delete().execute()
    database.close()

    salt = "randomsalt"
    
    # Create the main test user (always exists)
    try:
        User.create(username='user', password_hash=pyargon2.hash('code', salt), salt=salt, email='user@test.com')
    except:
        pass

    # Create additional fake users
    usernames = ['user']
    for _ in range(5):
        username = fake.user_name()
        try:
            User.create(
                username=username,
                password_hash=pyargon2.hash(fake.password(), salt),
                salt=salt,
                email=fake.unique.email()
            )
            usernames.append(username)
        except:
            pass

    # Create projects
    project_data = [
        {'id': 'FRO', 'name': 'Frontend', 'icon': 'ph ph-browser', 'color': 'blue'},
        {'id': 'BAC', 'name': 'Backend', 'icon': 'ph ph-database', 'color': 'purple'},
        {'id': 'MOB', 'name': 'Mobile', 'icon': 'ph ph-device-mobile', 'color': 'green'},
        {'id': 'INF', 'name': 'Infrastructure', 'icon': 'ph ph-cloud', 'color': 'orange'},
        {'id': 'DOC', 'name': 'Documentation', 'icon': 'ph ph-book-open', 'color': 'teal'},
    ]
    project_ids = []
    for proj in project_data:
        try:
            Project.create(**proj)
            project_ids.append(proj['id'])
        except:
            pass

    # Create tickets
    statuses = ['open', 'in-progress', 'review', 'closed']
    priorities = ['low', 'medium', 'high', 'urgent']
    ticket_ids = []

    for i in range(20):
        project_id = random.choice(project_ids)
        ticket_id = f"{project_id}-{100 + i}"
        try:
            Ticket.create(
                id=ticket_id,
                title=fake.sentence(nb_words=5)[:-1],  # Remove trailing period
                description=fake.sentence(nb_words=12),
                body=fake.paragraph(nb_sentences=5),
                status=random.choice(statuses),
                priority=random.choice(priorities),
                project=project_id,
                created_at=random_time()
            )
            ticket_ids.append(ticket_id)
        except Exception as e:
            print(e)

    # Assign users to tickets
    for ticket_id in ticket_ids:
        # Assign 1-3 random users to each ticket
        assigned_users = random.sample(usernames, k=random.randint(1, min(3, len(usernames))))
        for username in assigned_users:
            try:
                UserTicketJoin.create(user=username, ticket=ticket_id)
            except:
                pass

    # Create comments on tickets
    for ticket_id in ticket_ids:
        # Add 0-4 comments per ticket
        for _ in range(random.randint(1, 20)):
            try:
                Comment.create(
                    ticket=ticket_id,
                    user=random.choice(usernames),
                    body=fake.paragraph(nb_sentences=random.randint(1, 3)),
                    created_at=random_time()
                )
            except:
                pass

    # Create ticket update messages
    update_types = [
        {'title': 'Status Changed', 'icon': 'ph ph-arrows-clockwise'},
        {'title': 'Priority Updated', 'icon': 'ph ph-warning'},
        {'title': 'Assignee Added', 'icon': 'ph ph-user-plus'},
        {'title': 'Comment Added', 'icon': 'ph ph-chat-circle'},
        {'title': 'Description Updated', 'icon': 'ph ph-pencil'},
    ]
    
    for ticket_id in ticket_ids:
        # Add 0-3 update messages per ticket
        for _ in range(random.randint(0, 3)):
            update_type = random.choice(update_types)
            try:
                TicketUpdateMessage.create(
                    ticket=ticket_id,
                    title=update_type['title'],
                    icon=update_type['icon'],
                    message=fake.sentence(nb_words=8),
                    created_at=random_time()
                )
            except:
                pass
    
    # Add labels
    label_names = ['bug', 'feature', 'urgent', 'low-priority', 'documentation']
    for label_name in label_names:
        try:
            Label.create(
                name=label_name,
                color=fake.color_name().lower()
            )
        except:
            pass
    
    # Assign labels to tickets
    for ticket_id in ticket_ids:
        # Assign 0-2 labels per ticket
        assigned_labels = random.sample(label_names, k=random.randint(0, min(2, len(label_names))))
        for label_name in assigned_labels:
            try:
                TicketLabelJoin.create(
                    ticket=ticket_id,
                    label=label_name
                )
            except:
                pass