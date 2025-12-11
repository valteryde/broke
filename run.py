
from app.server import run_test_app
from app.utils.app import create_app
    
# Create app instance
app = create_app()

if __name__ == '__main__':
    run_test_app(app)
