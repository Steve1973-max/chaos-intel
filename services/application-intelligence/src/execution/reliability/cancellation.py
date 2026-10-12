import threading
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from .errors import OrchestrationCancelledError

class CancellationRequest(BaseModel):
    reason: str
    source: str
    requested_at: str

class CancellationManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancellation: Optional[CancellationRequest] = None

    def request_cancellation(self, reason: str, source: str = "manual"):
        with self._lock:
            if self._cancellation is None:
                self._cancellation = CancellationRequest(
                    reason=reason,
                    source=source,
                    requested_at=datetime.now(timezone.utc).isoformat()
                )

    def check_cancelled(self):
        with self._lock:
            if self._cancellation:
                raise OrchestrationCancelledError(f"Orchestration cancelled by {self._cancellation.source}: {self._cancellation.reason}")
