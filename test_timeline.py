import sys, os, json
sys.path.insert(0, os.getcwd())

from run import app
from app.views.news import build_timeline_events, build_reports_summary

with app.app_context():
    # Make sure we fetch enough events to hit all possible types (limit=50000 to get them all)
    try:
        summary = build_reports_summary(days=3650) # Get all time
        data = build_timeline_events(project_id=None, days=0, detailed=True, limit=50000)
        from flask import render_template
        from app.utils.models import User, Project
        
        user = User.select().first()
        projects = list(Project.select().order_by(Project.name))
        
        with app.test_request_context('/timeline'):
             render_template(
                'timeline.jinja2',
                user=user,
                page='reports',
                summary=summary,
                projects=projects,
                project=None,
                events=data['events'],
                events_json=json.dumps(data['events']),
                activity_by_day=json.dumps(data['activity_by_day']),
                query_suffix="",
                compact_url="",
                detailed_url="",
                detail_mode=True,
                selected_days='all',
                has_more_events=False,
                total_events=data['total_events'],
                date_range=data['date_range'],
                tickets_created=data['tickets_created'],
                tickets_closed=data['tickets_closed'],
                tickets_in_progress=data['tickets_in_progress'],
                total_comments=data['total_comments'],
                total_errors=data['total_errors'],
                errors_resolved=data['errors_resolved'],
                active_users=data['active_users'],
                effort_tickets=data['effort_tickets'],
                effort_bugs=data['effort_bugs'],
                effort_features=data['effort_features'],
                top_contributors=data['top_contributors'],
            )
        print("Successfully rendered entire timeline!")
    except Exception as e:
        import traceback
        traceback.print_exc()
