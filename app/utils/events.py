import threading

class EventBus:
    def __init__(self):
        self._subscribers = {}

    def subscribe(self, event_type, handler):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def emit(self, event_type, **kwargs):
        if event_type in self._subscribers:
            for handler in self._subscribers[event_type]:
                # Run the handler in a new thread so it is asynchronous
                threading.Thread(target=handler, kwargs=kwargs, daemon=True).start()

# Global event bus instance
bus = EventBus()
