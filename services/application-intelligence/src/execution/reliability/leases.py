from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import threading
import uuid
from .errors import LeaseAcquisitionError, LeaseOwnershipError

class Lease(BaseModel):
    lease_id: str
    run_id: str
    owner_id: str
    acquired_at: str
    expires_at: Optional[str] = None
    status: str = "acquired" # acquired, released, expired
    metadata: Dict[str, Any] = Field(default_factory=dict)

class LeaseManager:
    """
    In-memory lease manager.
    Guarantees mutual exclusion only within its shared instance/process.
    Do not claim cross-process safety.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._leases: Dict[str, Lease] = {} # run_id -> Lease

    def acquire(self, run_id: str, owner_id: str, timeout_sec: Optional[float] = None) -> Lease:
        with self._lock:
            now = datetime.now(timezone.utc)
            
            # Check existing
            if run_id in self._leases:
                existing = self._leases[run_id]
                if existing.status == "acquired":
                    # Check expiration
                    if existing.expires_at:
                        exp_dt = datetime.fromisoformat(existing.expires_at)
                        if now >= exp_dt:
                            existing.status = "expired"
                        else:
                            raise LeaseAcquisitionError(f"Run {run_id} is already acquired by {existing.owner_id}")
                    else:
                        raise LeaseAcquisitionError(f"Run {run_id} is already acquired by {existing.owner_id}")

            expires_at = (now + timedelta(seconds=timeout_sec)).isoformat() if timeout_sec else None
            lease = Lease(
                lease_id=str(uuid.uuid4()),
                run_id=run_id,
                owner_id=owner_id,
                acquired_at=now.isoformat(),
                expires_at=expires_at,
                status="acquired"
            )
            self._leases[run_id] = lease
            return lease

    def release(self, run_id: str, lease_id: str, owner_id: str):
        with self._lock:
            if run_id not in self._leases:
                return # nothing to release

            existing = self._leases[run_id]
            if existing.lease_id != lease_id:
                raise LeaseOwnershipError(f"Lease ID mismatch. Provided {lease_id}, expected {existing.lease_id}")
            if existing.owner_id != owner_id:
                raise LeaseOwnershipError(f"Owner ID mismatch. Provided {owner_id}, expected {existing.owner_id}")
            if existing.status == "acquired":
                existing.status = "released"

class LeaseContext:
    def __init__(self, manager: LeaseManager, run_id: str, owner_id: str, timeout_sec: Optional[float] = None):
        self.manager = manager
        self.run_id = run_id
        self.owner_id = owner_id
        self.timeout_sec = timeout_sec
        self.lease: Optional[Lease] = None

    def __enter__(self) -> Lease:
        self.lease = self.manager.acquire(self.run_id, self.owner_id, self.timeout_sec)
        return self.lease

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lease:
            self.manager.release(self.run_id, self.lease.lease_id, self.owner_id)
