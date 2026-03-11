import os
import sys

sys.path.insert(0, os.getcwd())
from run import app
from app.utils.models import User
from flask import render_template
import json
from app.views.news import build_timeline_events, build_reports_summary, _timeline_query_suffix, _timeline_mode_url

with app.app_context():
    try:
        user = User.select().first()
        summary = build_reports_summary(days=30)
        data = build_timeline_events(project_id=None, days=30, detailed=False)
        from app.utils.models import Project
        projects = list(Project.select().order_by(Project.name))
        
        with app.test_request_context('/timeline'):
            try:
                html = render_template(
                    'timeline.jinja2',
                    user=user,
                    page='reports',
                    summary=summary,
                    projects=projects,
                    project=None,
                    events=data['events'],
                    events_json=json.dumps(data['events']),
                    activity_by_day=json.dumps(data['activity_by_day']),
                    query_suffix=_timeline_query_suffix(30, False),
                    compact_url=_timeline_mode_url('/timeline', 30, False),
                    detailed_url=_timeline_mode_url('/timeline', 30, True),
                    detail_mode=False,
                    selected_days='30',
                    has_more_events=len(data['events']) > 50,
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
                print("Rendered without 500 error:", len(html))
            except Exception as render_e:
                print("500 Error during render!")
                import traceback
                traceback.print_exc()
    except Exception as e:
        import traceback
        traceback.print_exc()

