import threading
import time


class EventTypes:
    USER_PASSWORD_RESET = "USER_PASSWORD_RESET"
    TICKET_CREATED = "TICKET_CREATED"
    TICKET_TRIAGED = "TICKET_TRIAGED"
    TICKET_STATUS_CHANGED = "TICKET_STATUS_CHANGED"
    TICKET_COMMENTED = "TICKET_COMMENTED"
    ANON_TICKET_SUBMITTED = "ANON_TICKET_SUBMITTED"


class EventBus:
    def __init__(self):
        self._subscribers = {}
        self._wildcard_subscribers = []

    def subscribe(self, event_type, handler):
        if event_type == "*":
            self._wildcard_subscribers.append(handler)
            return

        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def emit(self, event_type, async_dispatch=True, **kwargs):
        event = {
            "event_type": event_type,
            "emitted_at": int(time.time()),
            **kwargs,
        }

        handlers = list(self._subscribers.get(event_type, [])) + list(self._wildcard_subscribers)
        for handler in handlers:
            if async_dispatch:
                thread = threading.Thread(target=handler, kwargs=event, daemon=True)
                thread.start()
            else:
                handler(**event)


# Global event bus instance
bus = EventBus()
