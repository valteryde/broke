import sys, os
sys.path.insert(0, os.getcwd())
from run import app
from app.views.news import build_reports_summary

with app.app_context():
    try:
        data = build_reports_summary(days=30)
        print("Success on build_reports_summary")
    except Exception as e:
        import traceback
        traceback.print_exc()

