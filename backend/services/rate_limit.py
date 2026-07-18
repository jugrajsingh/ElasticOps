"""In-process login rate limiting.

A sliding-window throttle keyed by ``ip:email`` with no external store — adequate for the
single-process deployment ElasticOps targets. Failed logins are recorded; once a key accumulates
``max_failures`` within ``window_seconds`` it is locked out (HTTP 429) until the oldest failures age
out of the window. A successful login resets the key. The clock is injectable for deterministic tests.
"""

import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException


class LoginThrottle:
    """In-process sliding-window login throttle keyed by ``ip:email``. No external store."""

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: int = 900,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._fails: dict[str, list[float]] = defaultdict(list)
        self._now: Callable[[], float] = now if now is not None else time.monotonic

    def _recent(self, key: str) -> list[float]:
        cutoff = self._now() - self._window
        self._fails[key] = [t for t in self._fails[key] if t >= cutoff]
        return self._fails[key]

    def check(self, key: str) -> None:
        """Raise ``HTTPException(429)`` if ``key`` has too many recent failures."""
        if len(self._recent(key)) >= self._max:
            raise HTTPException(429, "Too many failed login attempts; try again later.")

    def record_failure(self, key: str) -> None:
        self._fails[key].append(self._now())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


login_throttle = LoginThrottle()
