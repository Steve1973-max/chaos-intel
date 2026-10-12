import time
from typing import Optional, Callable
from .errors import OrchestrationTimeoutError

class TimeoutManager:
    def __init__(self, timeout_sec: float, clock: Optional[Callable[[], float]] = None):
        import math
        if timeout_sec is None or math.isnan(timeout_sec) or math.isinf(timeout_sec) or timeout_sec <= 0:
            raise ValueError("Timeout must be a finite positive number.")
        self.timeout_sec = timeout_sec
        self.clock = clock or time.monotonic
        self.start_time = self.clock()

    def check(self):
        elapsed = self.clock() - self.start_time
        if elapsed > self.timeout_sec:
            raise OrchestrationTimeoutError(f"Orchestration timed out after {elapsed:.2f} seconds (limit: {self.timeout_sec}s).")
