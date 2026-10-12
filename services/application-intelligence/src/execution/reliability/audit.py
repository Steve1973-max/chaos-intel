from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import uuid
import threading

class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    application_id: str
    experiment_id: str
    event_type: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor: str = "system"
    previous_state: Optional[str] = None
    current_state: str
    outcome: str
    reason: Optional[str] = None
    correlation_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class AuditLogger:
    """
    In-memory audit logger.
    Not durable. Does not record RUNNING or COMPLETED merely because a dry-run plan was produced.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._events: List[AuditEvent] = []

    def _redact(self, data: Any) -> Any:
        import copy
        secret_keys = {"password", "secret", "token", "api_key", "private_key", 
                       "access_key", "credential", "authorization", "client_secret", "connection_string"}
        
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if any(sec in k.lower() for sec in secret_keys):
                    redacted[k] = "***REDACTED***"
                else:
                    redacted[k] = self._redact(v)
            return redacted
        elif isinstance(data, list):
            return [self._redact(item) for item in data]
        elif isinstance(data, str) and any(scheme in data.lower() for scheme in ["mongodb://", "postgres://", "mysql://"]):
            return "***REDACTED***"
        return copy.deepcopy(data)

    def log(self, event: AuditEvent):
        # Do not include secrets in metadata
        with self._lock:
            # We must not mutate the caller's object
            safe_event = event.model_copy(deep=True)
            safe_event.metadata = self._redact(safe_event.metadata)
            self._events.append(safe_event)
            
    def get_events(self, run_id: str) -> List[AuditEvent]:
        with self._lock:
            return [e for e in self._events if e.run_id == run_id]
