
from utils.app import app
from views import *
from utils.models import initialize_db, setup_test_data
from _thread import start_new_thread
import subprocess
import sentry_sdk
from config import dogfood_dsn, eat_your_own_dogfood

if eat_your_own_dogfood:
    sentry_sdk.init(
        dsn=dogfood_dsn,
        traces_sample_rate=1.0
    )

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('images/favicon/favicon.ico')

@app.route('/')
def index():
    return redirect('/news')

def run_error_populator():
    
    time.sleep(5)  # Give the server time to start
    subprocess.run(["python3", "scripts/populate_error_messages.py"])

initialize_db()

if __name__ == '__main__':
    setup_test_data()
    
    start_new_thread(run_error_populator, ())

    @app.route('/force-error')
    def force_error():
        raise Exception("This is a forced error for testing Sentry integration.")
    

    app.run(debug=True, port=5000)


