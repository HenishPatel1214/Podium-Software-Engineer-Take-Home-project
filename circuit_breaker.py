import threading
import time
from collections import deque
from config import CircuitBreaker as CircuitBreakerConfig


class CircuitBreakerState:
    """
    Tracks failure counts for a single route and trips the circuit when
    the failure threshold is exceeded within the configured time window.

    States:
      closed  — normal operation, requests flow through
      open    — circuit tripped, requests are rejected immediately
      (after cooldown, automatically resets back to closed)
    """

    def __init__(self, cfg: CircuitBreakerConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._failures: deque = deque()    # timestamps of recent failures (oldest at left)
        self._tripped_at: float | None = None

    def is_open(self) -> tuple[bool, float]:
        """Returns (is_open, seconds_remaining_in_cooldown)."""
        with self._lock:
            if self._tripped_at is None:
                return False, 0.0

            elapsed = time.time() - self._tripped_at
            remaining = self.cfg.cooldown - elapsed

            if remaining <= 0:
                # Cooldown finished — reset to closed
                self._tripped_at = None
                self._failures.clear()
                return False, 0.0

            return True, remaining

    def record_failure(self):
        with self._lock:
            now = time.time()
            cutoff = now - self.cfg.window
            # Evict failures that have fallen outside the window (O(1) amortized)
            while self._failures and self._failures[0] <= cutoff:
                self._failures.popleft()
            self._failures.append(now)

            # Only trip once — don't reset _tripped_at on subsequent failures, or
            # the cooldown clock would restart on every new failure and never expire.
            if len(self._failures) >= self.cfg.threshold and self._tripped_at is None:
                self._tripped_at = now

    def record_success(self):
        with self._lock:
            self._failures.clear()
