"""One bounded snapshot per process, shared by viewers, with failure backoff."""
import copy
import threading
import time


class SnapshotCache:
    def __init__(self, ttl=5, clock=time.monotonic):
        self.ttl = max(2.0, float(ttl))
        self.clock = clock
        self.lock = threading.RLock()
        self.key = None
        self.data = None
        self.checked = 0
        self.observed = None
        self.error = None
        self.failures = 0
        self.retry_at = 0
        self.collections = 0

    def invalidate(self):
        with self.lock:
            self.key, self.data, self.error = None, None, None
            self.retry_at = self.failures = 0

    def get(self, key, collect, fresh=False):
        # Single flight: simultaneous clients never fan out requests to AMI.
        with self.lock:
            now = self.clock()
            if key != self.key:
                self.invalidate()
                self.key = key
            if self.error is not None and now < self.retry_at:
                raise RuntimeError('pbx_retry_backoff') from self.error
            if not fresh and self.data is not None and now - self.checked < self.ttl:
                return copy.deepcopy(self.data), self.observed
            try:
                self.collections += 1
                result = collect()
            except Exception as exc:
                self.data, self.observed, self.error = None, None, exc
                self.failures += 1
                self.retry_at = self.clock() + min(30, 2 ** min(self.failures, 5))
                raise
            self.data = copy.deepcopy(result)
            self.checked, self.observed = self.clock(), time.time()
            self.error, self.failures, self.retry_at = None, 0, 0
            return copy.deepcopy(self.data), self.observed
