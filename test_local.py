import os
import sys

sys.path.insert(0, os.getcwd())
from run import app
from app.utils.models import User
from app.views.news import build_timeline_events, build_reports_summary

with app.app_context():
    try:
        data = build_reports_summary(days=30)
        print("Success on build_reports_summary")
        timeline = build_timeline_events(project_id=None, days=30, detailed=False)
        print("Success on build_timeline_events")
    except Exception as e:
        import traceback
        traceback.print_exc()

