
from .utils.models import initialize_db, setup_test_data
import subprocess
import sentry_sdk
from .config import dogfood_dsn, eat_your_own_dogfood
import time

if eat_your_own_dogfood:
    sentry_sdk.init(
        dsn=dogfood_dsn,
        traces_sample_rate=1.0
    )


def run_error_populator():
    time.sleep(5)  # Give the server time to start
    subprocess.run(["python3", "scripts/populate_error_messages.py"])


def run_test_app(app):
    """Run the Flask application in test mode"""
    # Initialize database
    initialize_db()
    setup_test_data()

    # start_new_thread(run_error_populator, ())

    @app.route('/force-error')
    def force_error():
        raise Exception("This is a forced error for testing Sentry integration.")

    # Run the app
    app.run(debug=True, port=5000)
