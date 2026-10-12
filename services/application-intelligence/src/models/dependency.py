from pydantic import BaseModel, Field
from typing import List, Optional
from .technology import Evidence

class Dependency(BaseModel):
    source_service_id: str
    target_service_id: Optional[str] = None
    dependency_type: str # http, database, cache, message_queue, filesystem, external_api, runtime, unknown
    name: str
    version: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)
