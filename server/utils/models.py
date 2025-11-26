
from peewee import Model, CharField, IntegerField, SqliteDatabase
from .path import path

database = SqliteDatabase(path('..', 'data', 'app.db'))

class BaseModel(Model):
    class Meta:
        database = database

class User(BaseModel):
    username = CharField(unique=True)
    password_hash = CharField()
    salt = CharField()
    email = CharField(unique=True)


MODELS = [
    User
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

