from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from .technology import Evidence

class Service(BaseModel):
    service_id: str
    application_id: str
    name: str
    type: str # frontend, backend, worker, scheduler, database, cache, message_broker, gateway, external, unknown
    technology: Optional[str] = None
    source_path: str
    entry_points: List[str] = Field(default_factory=list)
    ports: List[int] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
