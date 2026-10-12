from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from .technology import Technology
from .service import Service
from .dependency import Dependency
from .api import Api
from .architecture import ArchitectureGraph
from .risk import RiskFinding
from .test_candidate import TestCandidate
from .experiment import ExperimentSpecification
from .safety import SafetyDecision
from .experiment_run import ExperimentRun

class ApplicationModel(BaseModel):
    application_id: str
    name: str
    repository_url: Optional[str] = None
    technologies: List[Technology] = Field(default_factory=list)
    services: List[Service] = Field(default_factory=list)
    dependencies: List[Dependency] = Field(default_factory=list)
    apis: List[Api] = Field(default_factory=list)
    architecture: ArchitectureGraph = Field(default_factory=lambda: ArchitectureGraph(nodes=[], edges=[]))
    risks: List[RiskFinding] = Field(default_factory=list)
    test_candidates: List[TestCandidate] = Field(default_factory=list)
    experiments: List[ExperimentSpecification] = Field(default_factory=list)
    safety_decisions: List[SafetyDecision] = Field(default_factory=list)
    experiment_runs: List[ExperimentRun] = Field(default_factory=list)
    analysis_version: str = "1.0.0"
    metadata: Dict[str, Any] = Field(default_factory=dict)
