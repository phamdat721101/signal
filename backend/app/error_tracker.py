import time
import traceback
from collections import deque


class ErrorTracker:
    def __init__(self, maxlen: int = 200):
        self._errors: deque[dict] = deque(maxlen=maxlen)

    def track(self, code: str, message: str, context: dict | None = None):
        stack = traceback.format_stack()[:-1]  # exclude this frame
        entry = {
            "code": code,
            "message": message[:500],
            "context": context or {},
            "stack": "".join(stack[-3:])[:1000],  # last 3 frames, capped
            "timestamp": time.time(),
            "count": 1,
        }
        # Deduplicate consecutive identical error codes
        if self._errors and self._errors[-1]["code"] == code:
            prev = self._errors[-1]
            prev["count"] += 1
            prev["timestamp"] = entry["timestamp"]
            prev["message"] = entry["message"]
            prev["context"] = entry["context"]
        else:
            self._errors.append(entry)

    def get_recent(self, n: int = 20) -> list[dict]:
        return list(self._errors)[-n:]

    def get_by_code(self, code: str, n: int = 10) -> list[dict]:
        return [e for e in self._errors if e["code"] == code][-n:]

    def summary(self) -> dict:
        codes: dict[str, int] = {}
        for e in self._errors:
            codes[e["code"]] = codes.get(e["code"], 0) + e["count"]
        return {"total_entries": len(self._errors), "by_code": codes}


error_tracker = ErrorTracker()
