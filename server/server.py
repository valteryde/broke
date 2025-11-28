
from utils.app import app
from views import *
from utils.models import initialize_db, setup_test_data
from _thread import start_new_thread
import subprocess

def run_error_populator():
    
    time.sleep(5)  # Give the server time to start
    subprocess.run(["python3", "scripts/populate_error_messages.py"])

if __name__ == '__main__':
    initialize_db()
    setup_test_data()
    
    start_new_thread(run_error_populator, ())


    app.run(debug=True)
