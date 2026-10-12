from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from .technology import Evidence

class ApiParameter(BaseModel):
    name: str
    location: str # path, query, header, cookie, unknown

class Api(BaseModel):
    api_id: str
    service_id: Optional[str] = None
    method: str # GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD
    path: str
    protocol: Optional[str] = "http"
    framework: Optional[str] = None
    source: Optional[str] = None
    parameters: List[ApiParameter] = Field(default_factory=list)
    request_body: Optional[Any] = None
    response_information: Optional[Any] = None
    auth_required: Optional[bool] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
