from ward import fixture, Scope
from app.utils.app import create_app
import faker
from app.utils.models import Ticket, Project


@fixture(scope=Scope.Test)
def fake() -> faker.Faker:
    return faker.Faker()


@fixture(scope=Scope.Global)
def client():
    app = create_app()
    with app.test_client() as client:
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
