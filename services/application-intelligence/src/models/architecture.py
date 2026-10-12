from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from .technology import Evidence

class GraphNode(BaseModel):
    node_id: str
    node_type: str
    name: str
    service_id: Optional[str] = None
    technology_references: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)

class GraphEdge(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    protocol: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ArchitectureGraph(BaseModel):
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
