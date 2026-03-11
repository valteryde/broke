import sys
import os

# Set up flask app context
from app.run import app
from app.views.news import build_reports_summary

with app.app_context():
    try:
        summary = build_reports_summary(days=30)
        print("Success")
    except Exception as e:
        import traceback
        traceback.print_exc()
