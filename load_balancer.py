import threading
from config import UpstreamTarget


class LoadBalancer:
    """
    Picks an upstream target for each request.

    Strategies:
      round_robin         — cycle through targets equally
      weighted_round_robin — repeat each target proportional to its weight
    """

    def __init__(self, targets: list[UpstreamTarget], strategy: str):
        self._lock = threading.Lock()
        self._counter = 0

        if strategy == "weighted_round_robin":
            # Expand targets by weight: weight=3 means 3 entries in the rotation
            self._rotation = []
            for t in targets:
                self._rotation.extend([t.url] * t.weight)
        else:
            self._rotation = [t.url for t in targets]

    def next_target(self) -> str:
        with self._lock:
            url = self._rotation[self._counter % len(self._rotation)]
            self._counter += 1
            return url
