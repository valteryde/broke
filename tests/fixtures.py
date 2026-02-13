from ward import fixture, Scope
from app.utils.app import create_app
import faker
import time
from app.utils.models import Ticket, Project, initialize_db, create_user


def create_test_project(project_id, name="Test Project", description="Test Description"):
    """Helper to create a project with all required fields"""
    return Project.create(
        id=project_id,
        name=name,
        description=description,
        icon="ph ph-test",
        color="#3b82f6"
    )


@fixture(scope=Scope.Test)
def fake() -> faker.Faker:
    return faker.Faker()


@fixture(scope=Scope.Global)
def app():
    """Create Flask app for testing"""
    # Initialize database for tests
    initialize_db()
    
    test_app = create_app()
    test_app.config['TESTING'] = True
    test_app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
    return test_app


@fixture(scope=Scope.Global)
def client(app=app):
    """Unauthenticated test client"""
    with app.test_client() as client:
        yield client


@fixture(scope=Scope.Test)
def auth_user(fake: faker.Faker = fake):
    """Create a test user for authentication"""
    username = f"testuser_{fake.uuid4()[:8]}"
    password = "testpassword123"
    # Make email unique with timestamp to avoid UNIQUE constraint errors
    email = f"test_{int(time.time() * 1000000)}@example.com"
    user = create_user(username, password, email)
    user.password = password  # Store plaintext for testing
    yield user
    # Cleanup handled by test scope


@fixture(scope=Scope.Test)
def auth_client(app=app, auth_user=auth_user):
    """Authenticated test client with logged-in user"""
    with app.test_client() as client:
        # Login the user via the callback endpoint
        response = client.post('/callback', data={
            'username': auth_user.username,
            'password': auth_user.password
        }, follow_redirects=False)
        # Verify login succeeded (should redirect)
        if response.status_code not in [302]:
            raise Exception(f"Login failed with status {response.status_code}")
        yield client
@fixture(scope=Scope.Test)
def test_project(fake: faker.Faker = fake):
    project = Project.create(
        id=str(fake.uuid4()), name=fake.word(), icon="ph ph-folder", color="blue"
    )
    yield project
    project.delete_instance(recursive=True, delete_nullable=True)


@fixture(scope=Scope.Test)
def test_ticket(fake: faker.Faker = fake, test_project: Project = test_project):
    ticket = Ticket.create(
        id=str(fake.uuid4()),
        title=fake.sentence(),
        description=fake.text(),
        project=test_project.id,
        status="todo",
        priority="medium",
    )
    yield ticket
    ticket.delete_instance(recursive=True, delete_nullable=True)
