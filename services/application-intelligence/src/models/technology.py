from pydantic import BaseModel, Field
from typing import List, Optional

class Evidence(BaseModel):
    source: str
    type: str
    detail: str

class Technology(BaseModel):
    name: str
    category: str
    version: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[Evidence]

class TechnologyInventory(BaseModel):
    technologies: List[Technology]
