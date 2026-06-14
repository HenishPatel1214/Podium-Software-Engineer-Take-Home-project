import threading
import time
from collections import deque
from config import RateLimit


class RateLimiter:
    """
    Thread-safe rate limiter supporting fixed-window and sliding-window strategies.

    Keys are strings like "ip:192.168.1.1:/api/users" or "global:/api/users".
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._fixed: dict[str, tuple[int, float]] = {}   # key -> (count, window_start)
        self._sliding: dict[str, deque] = {}              # key -> deque of timestamps

    def is_allowed(self, key: str, cfg: RateLimit) -> bool:
        with self._lock:
            if cfg.strategy == "sliding_window":
                return self._sliding_check(key, cfg)
            return self._fixed_check(key, cfg)

    def _fixed_check(self, key: str, cfg: RateLimit) -> bool:
        now = time.time()
        count, start = self._fixed.get(key, (0, now))

        if now - start >= cfg.window:
            # Window expired — start a new one
            self._fixed[key] = (1, now)
            return True

        if count < cfg.requests:
            self._fixed[key] = (count + 1, start)
            return True

        return False

    def _sliding_check(self, key: str, cfg: RateLimit) -> bool:
        now = time.time()
        if key not in self._sliding:
            self._sliding[key] = deque()

        window = self._sliding[key]
        cutoff = now - cfg.window

        # Evict timestamps that have fallen outside the window
        while window and window[0] <= cutoff:
            window.popleft()

        if len(window) < cfg.requests:
            window.append(now)
            return True

        return False
