import logging
import time
import uuid

import pyargon2
from peewee import (
    AutoField,
    CharField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

from .path import data_path

logger = logging.getLogger(__name__)
logger.info(f"Database path: {data_path('app.db')}")

database = SqliteDatabase(data_path("app.db"))


class BaseModel(Model):
    class Meta:
        database = database


class User(BaseModel):
    username = CharField(primary_key=True)
    password_hash = CharField()
    salt = CharField()
    email = CharField(unique=True)
    admin = IntegerField(default=0)


def create_user(username: str, password, email: str, admin: int = 0):
    User.create_table(safe=True)

    salt = uuid.uuid4().hex
    password_hash = pyargon2.hash(password, salt)
    user = User.create(
        username=username, password_hash=password_hash, salt=salt, email=email, admin=admin
    )
    return user


class UserCreateToken(BaseModel):  # should be deleted after use
    token = CharField(primary_key=True)
    created_at = IntegerField(default=lambda: int(time.time()))
    role = IntegerField(default=0)  # For future use
    name = CharField(null=True)  # For friendly identification of the invite


class PasswordResetToken(BaseModel):
    token = CharField(primary_key=True)
    user = CharField()
    created_at = IntegerField(default=lambda: int(time.time()))


class DesktopHandshakeToken(BaseModel):
    token = CharField(primary_key=True)
    created_at = IntegerField(default=lambda: int(time.time()))
    expires_at = IntegerField()
    used = IntegerField(default=0)


class DeviceToken(BaseModel):
    id = AutoField(primary_key=True)
    user = ForeignKeyField(User, backref="device_tokens")
    device_id = CharField(index=True)
    device_name = CharField()
    token_hash = CharField(index=True)
    created_at = IntegerField(default=lambda: int(time.time()))
    expires_at = IntegerField()
    last_used = IntegerField(null=True)
    revoked = IntegerField(default=0)

    class Meta:  # type: ignore
        indexes = ((("user", "device_id", "revoked"), False),)


class Project(BaseModel):
    id = CharField(primary_key=True)
    name = CharField()
    icon = CharField()  # classes for icons (like ph ph-* or fa fa-*)
    color = CharField()  # i do not know if i will use this
    # Optional JSON for future per-project options
    settings = TextField(default="{}")
    archived = IntegerField(default=0)  # 1 = hidden from selectors; existing tickets unchanged


def active_projects_ordered():
    """Projects available for new tickets, intake, and project pickers."""
    return Project.select().where(Project.archived == 0).order_by(Project.name)


class ProjectPart(BaseModel):
    id = AutoField(primary_key=True)
    project = ForeignKeyField(Project, backref="parts")
    name = CharField()
    description = CharField()

    class Meta:  # type: ignore
        indexes = ((("project", "name"), True),)


class ErrorGroup(BaseModel):
    """Groups similar errors together by fingerprint"""

    id = AutoField(primary_key=True)
    part = ForeignKeyField(ProjectPart, backref="error_groups")
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
    status = CharField(default="unresolved")  # unresolved, resolved, ignored

    class Meta:  # type: ignore
        indexes = ((("part", "fingerprint"), True),)  # Unique per part


class ErrorOccurrence(BaseModel):
    """Individual occurrence timestamps for an error group"""

    id = AutoField(primary_key=True)
    error_group = ForeignKeyField(ErrorGroup, backref="occurrences")
    timestamp = IntegerField(default=lambda: int(time.time()))
    event_id = CharField(null=True)  # Sentry event_id if provided


class Session(BaseModel):
    """Session data for crash-free rate tracking"""

    id = AutoField(primary_key=True)
    part = ForeignKeyField(ProjectPart, backref="sessions")
    session_id = CharField(index=True)
    status = CharField()  # ok, crashed, errored, abnormal
    started = IntegerField()
    duration = IntegerField(null=True)
    errors = IntegerField(default=0)
    release = CharField(null=True)
    environment = CharField(null=True)

    class Meta:  # type: ignore
        indexes = ((("part", "session_id"), True),)


class Transaction(BaseModel):
    """Performance transaction data"""

    id = AutoField(primary_key=True)
    part = ForeignKeyField(ProjectPart, backref="transactions")
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
    error_group = ForeignKeyField(ErrorGroup, backref="attachments", null=True)
    filename = CharField()
    content_type = CharField(null=True)
    data = CharField()  # Base64 encoded or path to file
    timestamp = IntegerField(default=lambda: int(time.time()))


# Legacy model - kept for backwards compatibility
class Error(BaseModel):
    part = ForeignKeyField(ProjectPart, backref="errors")
    data = CharField()  # Json
    created_at = IntegerField(default=lambda: int(time.time()))


class WorkCycle(BaseModel):
    """Time-boxed focus period for grouping tickets (no sprint/scrum terminology in UI)."""

    id = AutoField(primary_key=True)
    name = CharField()
    goal = TextField(null=True)
    project = CharField(null=True, index=True)  # null = workspace-wide
    starts_at = IntegerField(null=True)
    ends_at = IntegerField(null=True)
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
    active = IntegerField(default=1)
    parent_ticket_id = CharField(null=True, index=True)
    work_cycle_id = IntegerField(null=True, index=True)
    ai_delegate = IntegerField(default=0)

    anonymous_secret = CharField(null=True, unique=True)


class UserTicketJoin(BaseModel):
    user = CharField()
    ticket = CharField()

    class Meta:  # type: ignore
        indexes = ((("user", "ticket"), True),)


class Comment(BaseModel):
    id = AutoField(primary_key=True)
    ticket = CharField()
    user = ForeignKeyField(User, backref="comments")
    body = CharField()
    created_at = IntegerField(default=lambda: int(time.time()))
    # 1 when posted via the agent API (display as AI/agent, not the token owner).
    via_agent = IntegerField(default=0)

    class Meta:  # type: ignore
        indexes = ((("ticket", "user"), False),)


class TicketUpdateMessage(BaseModel):
    ticket = CharField()
    title = CharField()
    icon = CharField()
    message = CharField()
    created_at = IntegerField(default=lambda: int(time.time()))
    author = ForeignKeyField(User, null=True)

    class Meta:  # type: ignore
        indexes = ((("ticket", "title"), False),)


class Label(BaseModel):
    name = CharField(primary_key=True)
    color = CharField()


class TicketLabelJoin(BaseModel):
    ticket = CharField()
    label = CharField()

    class Meta:  # type: ignore
        indexes = ((("ticket", "label"), True),)


# ============ Settings Models ============


class UserSettings(BaseModel):
    """User preferences and settings"""

    user = CharField(primary_key=True)  # References User.username

    # Appearance
    theme = CharField(default="light")  # light, dark, system
    compact_mode = IntegerField(default=0)
    animations = IntegerField(default=1)

    # Defaults
    home_page = CharField(default="news")  # news, tickets, errors, timeline
    default_ticket_view = CharField(default="list")  # list, board, table

    # Locale
    timezone = CharField(default="UTC")
    date_format = CharField(default="dmy")  # mdy, dmy, ymd

    # Profile
    display_name = CharField(null=True)

    # Notification settings as JSON
    notification_settings = TextField(default="{}")


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
    webhook = ForeignKeyField(Webhook, backref="deliveries")

    event = CharField()
    response_code = IntegerField()
    status = CharField()  # success, error
    timestamp = IntegerField(default=lambda: int(time.time()))


class APIToken(BaseModel):
    """API tokens for programmatic access"""

    id = AutoField(primary_key=True)
    user = ForeignKeyField(User, backref="api_tokens")

    token_hash = CharField()  # SHA256 hash of the token
    token_preview = CharField()  # First 8 chars for display

    last_used = IntegerField(null=True)
    created_at = IntegerField(default=lambda: int(time.time()))


class AgentToken(BaseModel):
    """Short-lived Bearer tokens for agents (Cursor, scripts) — no CSRF; scope-limited."""

    id = AutoField(primary_key=True)
    user = ForeignKeyField(User, backref="agent_tokens")

    token_hash = CharField(index=True)
    token_preview = CharField()
    expires_at = IntegerField(index=True)
    scopes = TextField(default="[]")  # JSON array, e.g. ["comment:write","ticket:write"]
    project = CharField(null=True, index=True)
    work_cycle_id = IntegerField(null=True, index=True)
    ticket_id = CharField(null=True, index=True)  # when set, token is limited to this ticket only
    created_at = IntegerField(default=lambda: int(time.time()))


class DSNToken(BaseModel):
    """Single DSN token for Sentry SDK authentication - only one can exist at a time"""

    id = AutoField(primary_key=True)

    # Legacy plaintext token field kept for backwards compatibility/migration only.
    token = CharField(null=True)
    token_hash = CharField(null=True)
    token_preview = CharField(null=True)

    created_at = IntegerField(default=lambda: int(time.time()))
    last_used = IntegerField(null=True)


class GlobalSetting(BaseModel):
    """Generic key-value store for global settings"""

    key = CharField(primary_key=True)
    value = TextField()  # JSON content


class NotificationEventLog(BaseModel):
    id = AutoField(primary_key=True)
    event_type = CharField(index=True)
    channel = CharField()
    status = CharField()  # success, error
    detail = TextField(null=True)
    created_at = IntegerField(default=lambda: int(time.time()))


# ============ Changelog Models ============


class ChangelogRelease(BaseModel):
    """A versioned or date-based changelog release containing Markdown content"""

    id = AutoField(primary_key=True)
    version = CharField(unique=True, null=True)  # e.g. "1.4.0", optional
    title = CharField(null=True)  # Optional release title
    content = TextField()  # The raw Markdown content for the release
    status = CharField(default="draft")  # draft or published
    created_at = IntegerField(default=lambda: int(time.time()))


MODELS = [
    User,
    WorkCycle,
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
    UserCreateToken,
    # Settings models
    UserSettings,
    Webhook,
    WebhookDelivery,
    APIToken,
    AgentToken,
    DSNToken,
    GlobalSetting,
    NotificationEventLog,
    # Changelog models
    ChangelogRelease,
    PasswordResetToken,
    DesktopHandshakeToken,
    DeviceToken,
]


def initialize_db():
    database.connect()
    database.create_tables(MODELS, safe=True)
    _ensure_ticket_parent_column()
    _ensure_work_cycle_schema()
    _ensure_ai_delegate_column()
    _ensure_comment_via_agent_column()
    _ensure_agent_token_ticket_id_column()
    _ensure_dsn_token_columns()
    _ensure_project_settings_column()
    _ensure_project_archived_column()
    database.close()


def _ensure_ticket_parent_column() -> None:
    """Backfill schema for older databases that predate parent_ticket_id."""
    columns = [row[1] for row in database.execute_sql("PRAGMA table_info(ticket);").fetchall()]
    if "parent_ticket_id" not in columns:
        database.execute_sql("ALTER TABLE ticket ADD COLUMN parent_ticket_id TEXT;")
        database.execute_sql(
            "CREATE INDEX IF NOT EXISTS ticket_parent_ticket_id ON ticket(parent_ticket_id);"
        )


def _ensure_work_cycle_schema() -> None:
    """Add ticket.work_cycle_id for DBs created before the field existed (table from create_tables)."""
    columns = [row[1] for row in database.execute_sql("PRAGMA table_info(ticket);").fetchall()]
    if "work_cycle_id" not in columns:
        database.execute_sql("ALTER TABLE ticket ADD COLUMN work_cycle_id INTEGER;")
        database.execute_sql(
            "CREATE INDEX IF NOT EXISTS ticket_work_cycle_id ON ticket(work_cycle_id);"
        )


def _ensure_ai_delegate_column() -> None:
    columns = [row[1] for row in database.execute_sql("PRAGMA table_info(ticket);").fetchall()]
    if "ai_delegate" not in columns:
        database.execute_sql("ALTER TABLE ticket ADD COLUMN ai_delegate INTEGER DEFAULT 0;")


def _ensure_comment_via_agent_column() -> None:
    columns = [row[1] for row in database.execute_sql("PRAGMA table_info(comment);").fetchall()]
    if "via_agent" not in columns:
        database.execute_sql("ALTER TABLE comment ADD COLUMN via_agent INTEGER DEFAULT 0;")


def _ensure_agent_token_ticket_id_column() -> None:
    columns = [row[1] for row in database.execute_sql("PRAGMA table_info(agenttoken);").fetchall()]
    if "ticket_id" not in columns:
        database.execute_sql("ALTER TABLE agenttoken ADD COLUMN ticket_id TEXT;")
        database.execute_sql(
            "CREATE INDEX IF NOT EXISTS agenttoken_ticket_id ON agenttoken(ticket_id);"
        )


def _ensure_dsn_token_columns() -> None:
    """Backfill schema for DSN token hardening fields on older databases."""
    columns = [row[1] for row in database.execute_sql("PRAGMA table_info(dsntoken);").fetchall()]

    if "token_hash" not in columns:
        database.execute_sql("ALTER TABLE dsntoken ADD COLUMN token_hash TEXT;")
    if "token_preview" not in columns:
        database.execute_sql("ALTER TABLE dsntoken ADD COLUMN token_preview TEXT;")


def _ensure_project_settings_column() -> None:
    columns = [row[1] for row in database.execute_sql("PRAGMA table_info(project);").fetchall()]
    if "settings" not in columns:
        database.execute_sql("ALTER TABLE project ADD COLUMN settings TEXT DEFAULT '{}';")


def _ensure_project_archived_column() -> None:
    columns = [row[1] for row in database.execute_sql("PRAGMA table_info(project);").fetchall()]
    if "archived" not in columns:
        database.execute_sql("ALTER TABLE project ADD COLUMN archived INTEGER DEFAULT 0;")


def setup_test_data():  # noqa: C901
    # Function to setup test data in the database
    import random

    import pyargon2
    from faker import Faker

    def random_time():
        """Generate a random timestamp within the past year"""
        return int(time.time() - random.randint(0, 31536000))

    fake = Faker()

    # Delete existing data
    database.connect()
    for model in MODELS:
        model.delete().execute()
    database.close()

    salt = "randomsalt"

    # Create the main test user (always exists)
    try:
        User.create(
            username="user",
            password_hash=pyargon2.hash("code", salt),
            salt=salt,
            email="user@test.com",
            admin=1,
        )
    except Exception:
        pass

    # Create additional fake users
    usernames = ["user"]
    for _ in range(5):
        username = fake.user_name()
        try:
            User.create(
                username=username,
                password_hash=pyargon2.hash(fake.password(), salt),
                salt=salt,
                email=fake.unique.email(),
                admin=0,
            )
            usernames.append(username)
        except Exception:
            pass

    # Create projects
    project_data = [
        {"id": "FRO", "name": "Frontend", "icon": "ph ph-browser", "color": "blue"},
        {"id": "BAC", "name": "Backend", "icon": "ph ph-database", "color": "purple"},
        {"id": "MOB", "name": "Mobile", "icon": "ph ph-device-mobile", "color": "green"},
        {"id": "INF", "name": "Infrastructure", "icon": "ph ph-cloud", "color": "orange"},
        {"id": "DOC", "name": "Documentation", "icon": "ph ph-book-open", "color": "teal"},
    ]
    project_ids = []
    for proj in project_data:
        try:
            Project.create(**proj)
            project_ids.append(proj["id"])
        except Exception:
            pass

    # Create tickets
    statuses = ["backlog", "todo", "in-progress", "in-review", "done", "closed", "duplicate"]
    priorities = ["low", "medium", "high", "urgent"]
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
                created_at=random_time(),
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
            except Exception:
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
                    created_at=random_time(),
                )
            except Exception:
                pass

    # Create ticket update messages
    update_types = [
        {"title": "Status Changed", "icon": "ph ph-arrows-clockwise"},
        {"title": "Priority Updated", "icon": "ph ph-warning"},
        {"title": "Assignee Added", "icon": "ph ph-user-plus"},
        {"title": "Comment Added", "icon": "ph ph-chat-circle"},
        {"title": "Description Updated", "icon": "ph ph-pencil"},
    ]

    for ticket_id in ticket_ids:
        # Add 0-3 update messages per ticket
        for _ in range(random.randint(0, 3)):
            update_type = random.choice(update_types)
            try:
                TicketUpdateMessage.create(
                    ticket=ticket_id,
                    title=update_type["title"],
                    icon=update_type["icon"],
                    message=fake.sentence(nb_words=8),
                    created_at=random_time(),
                )
            except Exception:
                pass

    # Add labels
    label_names = ["bug", "feature", "urgent", "low-priority", "documentation"]
    for label_name in label_names:
        try:
            Label.create(name=label_name, color=fake.color_name().lower())
        except Exception:
            pass

    # Assign labels to tickets
    for ticket_id in ticket_ids:
        # Assign 0-2 labels per ticket
        assigned_labels = random.sample(label_names, k=random.randint(0, min(2, len(label_names))))
        for label_name in assigned_labels:
            try:
                TicketLabelJoin.create(ticket=ticket_id, label=label_name)
            except Exception:
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
