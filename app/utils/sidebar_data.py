
from ..utils.models import ErrorGroup, Comment, TicketUpdateMessage, Ticket
import time

def get_sidebar_data(user):
    """
    Fetches a single news/headline item for the sidebar.
    Priority:
    1. Unresolved Errors (if any)
    2. Latest Activity (Comment or Update)
    3. Fallback
    """
    try:
        # 1. Check for Unresolved Errors
        unresolved_count = ErrorGroup.select().where(ErrorGroup.status == 'unresolved').count()
        if unresolved_count > 0:
            # Get the most recent unresolved error to link to
            latest_error = ErrorGroup.select().where(ErrorGroup.status == 'unresolved').order_by(ErrorGroup.last_seen.desc()).first()
            error_link = '/errors'
            if latest_error and latest_error.part:
                try:
                    error_link = f"/errors/{latest_error.part.project.id}/{latest_error.part.id}/{latest_error.id}"
                except:
                    pass

            return {
                'title': 'System Alert',
                'icon': 'ph-bug-beetle',
                'text': f"{unresolved_count} Unresolved Error{'s' if unresolved_count != 1 else ''}",
                'type': 'error',
                'link': error_link
            }

        # 2. Check for Latest Activity
        # Get recent comment
        last_comment = Comment.select().order_by(Comment.created_at.desc()).first()
        # Get recent update
        last_update = TicketUpdateMessage.select().order_by(TicketUpdateMessage.created_at.desc()).first()

        latest_event = None
        if last_comment and last_update:
            if last_comment.created_at >= last_update.created_at:
                latest_event = ('comment', last_comment)
            else:
                latest_event = ('update', last_update)
        elif last_comment:
            latest_event = ('comment', last_comment)
        elif last_update:
            latest_event = ('update', last_update)

        if latest_event:
            evt_type, evt = latest_event
            
            # Resolve ticket project for link
            ticket_item = Ticket.get_or_none(Ticket.id == evt.ticket)
            ticket_link = '#'
            if ticket_item:
                ticket_link = f"/tickets/{ticket_item.project}/{ticket_item.id}"

            if evt_type == 'comment':
                return {
                    'title': 'New Comment',
                    'icon': 'ph-chat-circle',
                    'text': f"{evt.user.username} on {evt.ticket}",
                    'type': 'info',
                    'link': ticket_link
                }
            else: # update
                return {
                    'title': 'Ticket Update',
                    'icon': 'ph-pencil',
                    'text': f"{evt.ticket}: {evt.message[:20]}{'...' if len(evt.message) > 20 else ''}",
                    'type': 'info',
                    'link': ticket_link
                }

        # 3. Fallback
        return {
            'title': 'All Clear',
            'icon': 'ph-check-circle',
            'text': 'No new activity',
            'type': 'success',
            'link': '/news'
        }

    except Exception as e:
        print(f"Error fetching sidebar data: {e}")
        return {
            'title': 'News',
            'icon': 'ph-newspaper',
            'text': 'System operational',
            'type': 'info'
        }
