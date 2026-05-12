"""Error tracker with circuit breaker, persistent crash logging, and auto-fix capabilities."""
import json
import logging
import os
import time
import traceback
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Any

# Persistent crash log — survives restarts
_LOG_DIR = Path(os.environ.get("LOG_DIR", "/tmp/signal-logs"))
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_crash_logger = logging.getLogger("signal.crash")
_crash_logger.setLevel(logging.ERROR)
_handler = RotatingFileHandler(_LOG_DIR / "crash.log", maxBytes=5_000_000, backupCount=3)
_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
_crash_logger.addHandler(_handler)


class CircuitBreaker:
    """Circuit breaker: CLOSED → OPEN (after failures) → HALF_OPEN (after cooldown)."""

    def __init__(self, failure_threshold: int = 5, cooldown: float = 60.0):
        self._threshold = failure_threshold
        self._cooldown = cooldown
        self._failures = 0
        self._last_failure: float = 0
        self._state = "closed"  # closed | open | half_open

    @property
    def is_open(self) -> bool:
        if self._state == "open" and time.time() - self._last_failure > self._cooldown:
            self._state = "half_open"
        return self._state == "open"

    def record_success(self):
        self._failures = 0
        self._state = "closed"

    def record_failure(self):
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self._threshold:
            self._state = "open"

    def reset(self):
        self._failures = 0
        self._state = "closed"

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        if self.is_open:
            raise RuntimeError(f"Circuit open — retry after {self._cooldown}s")
        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise


class ErrorTracker:
    def __init__(self, maxlen: int = 200):
        self._errors: deque[dict] = deque(maxlen=maxlen)
        self._service_errors: dict[str, list[float]] = {}  # service → timestamps
        self._breakers: dict[str, CircuitBreaker] = {}

    def track(self, code: str, message: str, context: dict | None = None):
        stack = "".join(traceback.format_stack()[-3:])[:1000]
        entry = {
            "code": code,
            "message": message[:500],
            "context": context or {},
            "stack": stack,
            "timestamp": time.time(),
            "count": 1,
        }
        # Persist to file (survives restarts)
        _crash_logger.error(json.dumps({"code": code, "message": message[:300],
                                         "context": context or {}, "stack": stack[:500]}))
        if self._errors and self._errors[-1]["code"] == code:
            self._errors[-1]["count"] += 1
            self._errors[-1]["timestamp"] = entry["timestamp"]
        else:
            self._errors.append(entry)
        # Track per-service for throttling
        service = (context or {}).get("service", code)
        self._service_errors.setdefault(service, []).append(time.time())
        # Trim old entries (keep last 5 min)
        cutoff = time.time() - 300
        self._service_errors[service] = [t for t in self._service_errors[service] if t > cutoff]

    def get_breaker(self, service: str, threshold: int = 5, cooldown: float = 60.0) -> CircuitBreaker:
        if service not in self._breakers:
            self._breakers[service] = CircuitBreaker(threshold, cooldown)
        return self._breakers[service]

    def should_throttle(self, service: str, max_errors: int = 3, window: float = 60.0) -> bool:
        """Returns True if service has too many recent errors — caller should back off."""
        timestamps = self._service_errors.get(service, [])
        cutoff = time.time() - window
        recent = sum(1 for t in timestamps if t > cutoff)
        return recent >= max_errors

    def get_backoff(self, service: str) -> float:
        """Exponential backoff in seconds based on recent error count."""
        timestamps = self._service_errors.get(service, [])
        cutoff = time.time() - 300
        recent = sum(1 for t in timestamps if t > cutoff)
        return min(2 ** min(recent, 6), 120.0)  # max 120s

    def get_recent(self, n: int = 20) -> list[dict]:
        return list(self._errors)[-n:]

    def summary(self) -> dict:
        codes: dict[str, int] = {}
        for e in self._errors:
            codes[e["code"]] = codes.get(e["code"], 0) + e["count"]
        throttled = [s for s in self._service_errors if self.should_throttle(s)]
        open_breakers = [s for s, b in self._breakers.items() if b.is_open]
        return {"total_entries": len(self._errors), "by_code": codes,
                "throttled_services": throttled, "open_circuits": open_breakers}


error_tracker = ErrorTracker()
