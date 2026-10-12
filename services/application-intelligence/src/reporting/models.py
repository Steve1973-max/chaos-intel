from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from ..models.technology import Technology
from ..models.service import Service
from ..models.dependency import Dependency
from ..models.api import Api
from ..models.architecture import ArchitectureGraph
from ..models.risk import RiskFinding
from ..models.test_candidate import TestCandidate
from ..models.experiment import ExperimentSpecification
from ..models.safety import SafetyDecision
from ..models.experiment_run import ExperimentRun

class ReportSummaries(BaseModel):
    total_technologies: int = 0
    total_services: int = 0
    total_dependencies: int = 0
    total_apis: int = 0
    risks_by_severity: Dict[str, int] = Field(default_factory=dict)
    test_candidates_by_type: Dict[str, int] = Field(default_factory=dict)
    test_candidates_by_priority: Dict[str, int] = Field(default_factory=dict)
    experiments_by_fault_type: Dict[str, int] = Field(default_factory=dict)
    safety_decisions_by_status: Dict[str, int] = Field(default_factory=dict)
    experiment_runs_by_state: Dict[str, int] = Field(default_factory=dict)

class ApplicationReport(BaseModel):
    report_version: str = "1.0.0"
    generator_version: str = "1.0.0"
    generated_at: str
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
    summaries: ReportSummaries = Field(default_factory=ReportSummaries)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
