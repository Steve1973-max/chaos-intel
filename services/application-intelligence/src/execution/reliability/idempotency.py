import hashlib
import json
import threading
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel
from .errors import IdempotencyConflictError, InvalidIdempotencyKeyError

class IdempotencyRecord(BaseModel):
    key: str
    fingerprint: str
    status: str = "in_progress" # in_progress, completed
    result: Optional[Any] = None

class IdempotencyManager:
    """
    In-memory idempotency manager.
    Guarantees apply only to the lifetime of this process.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._records: Dict[str, IdempotencyRecord] = {}

    def compute_fingerprint(self, payload: Dict[str, Any]) -> str:
        """
        Compute a canonical, deterministic hash of the semantic payload.
        Do not include secrets.
        """
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def record_request(self, key: str, fingerprint: str) -> Tuple[bool, Optional[Any]]:
        """
        Returns (is_duplicate, result)
        If duplicate and result is None, it means the request is currently in progress.
        """
        if not key or not isinstance(key, str):
            raise InvalidIdempotencyKeyError("Key must be a non-empty string.")

        with self._lock:
            if key in self._records:
                record = self._records[key]
                if record.fingerprint != fingerprint:
                    raise IdempotencyConflictError(f"Idempotency key {key} reused with different fingerprint.")
                
                if record.status == "in_progress":
                    return True, None
                    
                return True, record.result

            # Create new
            self._records[key] = IdempotencyRecord(key=key, fingerprint=fingerprint)
            return False, None

    def store_result(self, key: str, result: Any):
        with self._lock:
            if key in self._records:
                self._records[key].status = "completed"
                self._records[key].result = result
