import time
from collections import deque


class ErrorTracker:
    def __init__(self, maxlen: int = 100):
        self._errors: deque[dict] = deque(maxlen=maxlen)

    def track(self, code: str, message: str, context: dict | None = None):
        entry = {"code": code, "message": message, "context": context or {}, "timestamp": time.time(), "count": 1}
        if self._errors and self._errors[-1]["code"] == code:
            self._errors[-1]["count"] += 1
            self._errors[-1]["timestamp"] = entry["timestamp"]
            self._errors[-1]["message"] = message
        else:
            self._errors.append(entry)

    def get_recent(self, n: int = 20) -> list[dict]:
        return list(self._errors)[-n:]


error_tracker = ErrorTracker()
