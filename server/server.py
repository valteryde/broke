
from app import app
from views import *
from utils.models import initialize_db, setup_test_data

if __name__ == '__main__':
    initialize_db()
    setup_test_data()
    app.run(debug=True)
