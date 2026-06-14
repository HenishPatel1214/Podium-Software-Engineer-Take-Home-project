import threading
import time
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
        self._failures: list[float] = []   # timestamps of recent failures
        self._tripped_at: float | None = None

    def is_open(self) -> tuple[bool, float]:
        """Returns (is_open, seconds_remaining_in_cooldown)."""
        with self._lock:
            if self._tripped_at is None:
                return False, 0.0

            elapsed = time.time() - self._tripped_at
            remaining = self.cfg.cooldown - elapsed

            if remaining <= 0:
                # Cooldown finished — reset
                self._tripped_at = None
                self._failures.clear()
                return False, 0.0

            return True, remaining

    def record_failure(self):
        with self._lock:
            now = time.time()
            cutoff = now - self.cfg.window
            self._failures = [t for t in self._failures if t > cutoff]
            self._failures.append(now)

            if len(self._failures) >= self.cfg.threshold:
                self._tripped_at = now

    def record_success(self):
        with self._lock:
            self._failures.clear()
