
from datetime import datetime
from peewee import Model, CharField, IntegerField, SqliteDatabase, DateTimeField, ForeignKeyField, AutoField, TextField
from .path import path
import time
import sentry_sdk


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



class ProjectPart(BaseModel):
    id = AutoField(primary_key=True)
    project = ForeignKeyField(Project, backref='parts')
    name = CharField()
    description = CharField()
    
    class Meta: # type: ignore
        indexes = (
            (('project', 'name'), True),
        )


class ErrorGroup(BaseModel):
    """Groups similar errors together by fingerprint"""
    id = AutoField(primary_key=True)
    part = ForeignKeyField(ProjectPart, backref='error_groups')
    fingerprint = CharField(index=True)  # Hash of message + stacktrace for grouping
    
    # Extracted fields for display/querying
    exception_type = CharField(null=True)  # e.g., "ValueError", "TypeError"
    exception_value = CharField(null=True)  # The error message
    culprit = CharField(null=True)  # File/function where error occurred
    
    # Platform/environment info (from first occurrence)
    platform = CharField(null=True)  # e.g., "python", "javascript"
    environment = CharField(null=True)  # e.g., "production", "development"
    release = CharField(null=True)  # Version/release tag
    
    # Full data storage
    stacktrace = CharField(null=True)  # Full stacktrace as JSON string
    contexts = CharField(null=True)  # OS, browser, device info as JSON
    tags = CharField(null=True)  # Tags as JSON
    extra = CharField(null=True)  # Extra data as JSON
    
    # Aggregation
    event_count = IntegerField(default=1)
    first_seen = IntegerField(default=lambda: int(time.time()))
    last_seen = IntegerField(default=lambda: int(time.time()))
    
    # Status for issue tracking
    status = CharField(default='unresolved')  # unresolved, resolved, ignored
    
    class Meta:  # type: ignore
        indexes = (
            (('part', 'fingerprint'), True),  # Unique per part
        )


class ErrorOccurrence(BaseModel):
    """Individual occurrence timestamps for an error group"""
    id = AutoField(primary_key=True)
    error_group = ForeignKeyField(ErrorGroup, backref='occurrences')
    timestamp = IntegerField(default=lambda: int(time.time()))
    event_id = CharField(null=True)  # Sentry event_id if provided


class Session(BaseModel):
    """Session data for crash-free rate tracking"""
    id = AutoField(primary_key=True)
    part = ForeignKeyField(ProjectPart, backref='sessions')
    session_id = CharField(index=True)
    status = CharField()  # ok, crashed, errored, abnormal
    started = IntegerField()
    duration = IntegerField(null=True)
    errors = IntegerField(default=0)
    release = CharField(null=True)
    environment = CharField(null=True)
    
    class Meta:  # type: ignore
        indexes = (
            (('part', 'session_id'), True),
        )


class Transaction(BaseModel):
    """Performance transaction data"""
    id = AutoField(primary_key=True)
    part = ForeignKeyField(ProjectPart, backref='transactions')
    transaction_id = CharField(index=True)
    name = CharField()  # Transaction name (e.g., route or function)
    op = CharField(null=True)  # Operation type (http, db, etc.)
    duration = IntegerField(null=True)  # Duration in milliseconds
    status = CharField(null=True)
    timestamp = IntegerField(default=lambda: int(time.time()))
    data = CharField(null=True)  # Additional data as JSON


class Attachment(BaseModel):
    """Attachments sent with events"""
    id = AutoField(primary_key=True)
    error_group = ForeignKeyField(ErrorGroup, backref='attachments', null=True)
    filename = CharField()
    content_type = CharField(null=True)
    data = CharField()  # Base64 encoded or path to file
    timestamp = IntegerField(default=lambda: int(time.time()))


# Legacy model - kept for backwards compatibility
class Error(BaseModel):
    part = ForeignKeyField(ProjectPart, backref='errors')
    data = CharField()  # Json
    created_at = IntegerField(default=lambda: int(time.time()))


class Ticket(BaseModel):
    id = CharField(primary_key=True)

    title = CharField()
    description = TextField()

    status = CharField()
    priority = CharField()

    project = CharField()

    error = ForeignKeyField(ErrorGroup, null=True)

    created_at = IntegerField(default=lambda: int(time.time()))


class UserTicketJoin(BaseModel):
    user = CharField()
    ticket = CharField()

    class Meta: # type: ignore
        indexes = (
            (('user', 'ticket'), True),
        )


class Comment(BaseModel):
    id = AutoField(primary_key=True)
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
    author = ForeignKeyField(User, null=True)

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


# ============ Settings Models ============

class UserSettings(BaseModel):
    """User preferences and settings"""
    user = CharField(primary_key=True)  # References User.username
    
    # Appearance
    theme = CharField(default='light')  # light, dark, system
    compact_mode = IntegerField(default=0)
    animations = IntegerField(default=1)
    
    # Defaults
    home_page = CharField(default='news')  # news, tickets, errors, timeline
    default_ticket_view = CharField(default='list')  # list, board, table
    
    # Locale
    timezone = CharField(default='UTC')
    date_format = CharField(default='dmy')  # mdy, dmy, ymd
    
    # Profile
    display_name = CharField(null=True)
    
    # Notification settings as JSON
    notification_settings = TextField(default='{}')
    
    # GitHub integration settings as JSON
    github_settings = TextField(default='{}')
    
    # Webhook secrets
    webhook_secret = CharField(null=True)
    github_webhook_secret = CharField(null=True)


class Webhook(BaseModel):
    """Outgoing webhooks configuration"""
    id = AutoField(primary_key=True)
    user = CharField()  # References User.username
    
    url = CharField()
    events = TextField()  # JSON array of event types
    secret = CharField(null=True)  # For signing payloads
    
    active = IntegerField(default=1)
    created_at = IntegerField(default=lambda: int(time.time()))
    last_triggered = IntegerField(null=True)


class WebhookDelivery(BaseModel):
    """Log of webhook delivery attempts"""
    id = AutoField(primary_key=True)
    webhook = ForeignKeyField(Webhook, backref='deliveries')
    
    event = CharField()
    response_code = IntegerField()
    status = CharField()  # success, error
    timestamp = IntegerField(default=lambda: int(time.time()))


class GitHubIntegration(BaseModel):
    """GitHub integration per project"""
    id = AutoField(primary_key=True)
    user = CharField()  # References User.username
    project = CharField()  # References Project.id
    
    repository = CharField(null=True)  # owner/repo format
    connected = IntegerField(default=0)
    
    # Settings
    create_tickets = IntegerField(default=1)
    link_commits = IntegerField(default=1)
    sync_comments = IntegerField(default=0)
    close_on_merge = IntegerField(default=1)
    
    created_at = IntegerField(default=lambda: int(time.time()))


class APIToken(BaseModel):
    """API tokens for programmatic access"""
    id = AutoField(primary_key=True)
    user = CharField()  # References User.username
    
    name = CharField()
    token_hash = CharField()  # SHA256 hash of the token
    token_preview = CharField()  # First 8 chars for display
    
    last_used = IntegerField(null=True)
    created_at = IntegerField(default=lambda: int(time.time()))


MODELS = [
    User,
    Ticket,
    UserTicketJoin,
    Project,
    Comment,
    TicketUpdateMessage,
    Label,
    TicketLabelJoin,
    ProjectPart,
    Error,
    ErrorGroup,
    ErrorOccurrence,
    Session,
    Transaction,
    Attachment,
    # Settings models
    UserSettings,
    Webhook,
    WebhookDelivery,
    GitHubIntegration,
    APIToken
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
                description=fake.paragraph(nb_sentences=10),
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

    # Create project parts
    for project_id in project_ids:
        for _ in range(random.randint(0, 4)):
            part_name = fake.word().capitalize() + " Service"
            try:
                ProjectPart.create(
                    project=project_id,
                    name=part_name,
                    description=fake.sentence(nb_words=10),
                )
            except Exception as e:
                print(e)
                continue

            # Create errors for the part
            # sentry_sdk.init(
            #     dsn=f"",
            #     # Add request headers and IP for users,
            #     # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
            #     send_default_pii=True,
            # )

            # for _ in range(random.randint(5, 20)):
            #     try:
            #         1 / 0  # Intentional error to generate a Sentry event
            #     except:
            #         sentry_sdk.capture_exception()
