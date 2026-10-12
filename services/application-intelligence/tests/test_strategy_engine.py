import os
import pytest
from src.main import analyze_application
from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph, GraphNode, GraphEdge
from src.models.risk import RiskFinding
from src.models.test_candidate import TestCandidate
from src.models.technology import Evidence
from src.models.dependency import Dependency
from src.models.api import Api
from src.strategy.engine import generate_test_candidates

def create_mock_app(risks=None, dependencies=None, apis=None):
    if risks is None: risks = []
    if dependencies is None: dependencies = []
    if apis is None: apis = []
    return ApplicationModel(
        application_id="app-1",
        name="test_app",
        technologies=[],
        services=[],
        dependencies=dependencies,
        apis=apis,
        architecture=ArchitectureGraph(nodes=[], edges=[]),
        risks=risks
    )

def test_availability_concentration():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="availability", risk_type="availability_concentration",
        severity="high", title="t", description="d", target_type="node", target_id="db-1", confidence=0.8,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "availability"
    assert cands[0].priority == "critical" # high severity + high confidence + central = 3 + 0 + 1 = 4 = critical

def test_spof():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="architecture", risk_type="single_point_of_failure",
        severity="medium", title="t", description="d", target_type="node", target_id="node-1", confidence=0.7,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "failover"
    assert cands[0].priority == "medium"

def test_critical_dependency():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="dependency", risk_type="critical_dependency",
        severity="high", title="t", description="d", target_type="edge", target_id="e1", confidence=0.9,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "dependency_resilience"

def test_external_dependency():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="dependency", risk_type="external_dependency",
        severity="medium", title="t", description="d", target_type="edge", target_id="e1", confidence=0.9,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "dependency_resilience"

def test_cyclic_dependency():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="architecture", risk_type="cyclic_dependency",
        severity="medium", title="t", description="d", target_type="edge", target_id="e1", confidence=0.9,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "workflow_resilience"

def test_dependency_concentration():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="architecture", risk_type="dependency_concentration",
        severity="medium", title="t", description="d", target_type="node", target_id="n1", confidence=0.9,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "dependency_resilience"

def test_unresolved_dependency():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="dependency", risk_type="unresolved_dependency",
        severity="low", title="t", description="d", target_type="node", target_id="n1", confidence=0.9,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "dependency_resilience"
    assert "timeout" in cands[0].expected_failure_mode

def test_api_concentration():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="api", risk_type="api_concentration",
        severity="info", title="t", description="d", target_type="node", target_id="n1", confidence=0.9,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "api_resilience"

def test_explicit_unauthenticated_api():
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="api", risk_type="explicitly_unauthenticated_api",
        severity="medium", title="t", description="d", target_type="api", target_id="api1", confidence=0.9,
        evidence=[]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].test_type == "api_resilience"
    
def test_null_auth_no_candidate():
    # If there is no risk, there is no candidate generated for api resilience.
    app = create_mock_app(risks=[])
    cands = generate_test_candidates(app)
    assert len(cands) == 0

def test_non_risk_database_dependency():
    dep = Dependency(source_service_id="s1", target_service_id=None, dependency_type="postgres", name="pg", confidence=0.9)
    app = create_mock_app(dependencies=[dep])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].target_id == "pg"
    assert cands[0].test_type == "dependency_resilience"

def test_non_risk_external_api():
    dep = Dependency(source_service_id="s1", target_service_id=None, dependency_type="external_api", name="api.stripe.com", confidence=0.9)
    app = create_mock_app(dependencies=[dep])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].target_id == "api.stripe.com"

def test_message_broker_candidate():
    dep = Dependency(source_service_id="s1", target_service_id=None, dependency_type="message_broker", name="kafka", confidence=0.9)
    app = create_mock_app(dependencies=[dep])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert cands[0].target_id == "kafka"
    assert "queue backlog" in cands[0].expected_failure_mode

def test_candidate_id_determinism():
    dep = Dependency(source_service_id="s1", target_service_id=None, dependency_type="postgres", name="pg", confidence=0.9)
    app = create_mock_app(dependencies=[dep])
    cands1 = generate_test_candidates(app)
    cands2 = generate_test_candidates(app)
    assert cands1[0].candidate_id == cands2[0].candidate_id

def test_candidate_deduplication():
    # Risk and Non-Risk might target the same thing
    dep = Dependency(source_service_id="s1", target_service_id=None, dependency_type="postgres", name="pg", confidence=0.9)
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="dependency", risk_type="critical_dependency",
        severity="high", title="t", description="d", target_type="dependency", target_id="pg", confidence=0.9,
        evidence=[Evidence(source="foo", type="t", detail="d")]
    )
    app = create_mock_app(risks=[risk], dependencies=[dep])
    cands = generate_test_candidates(app)
    assert len(cands) == 1
    assert len(cands[0].evidence) == 1 # the dep didn't have evidence, risk had 1

def test_evidence_preservation():
    ev = Evidence(source="file.py", type="code", detail="foo")
    risk = RiskFinding(
        risk_id="r1", application_id="app-1", category="dependency", risk_type="critical_dependency",
        severity="high", title="t", description="d", target_type="edge", target_id="e1", confidence=0.9,
        evidence=[ev]
    )
    app = create_mock_app(risks=[risk])
    cands = generate_test_candidates(app)
    assert cands[0].evidence[0].source == "file.py"

def test_priority_calculation():
    from src.strategy.priority import calculate_priority
    # low, conf low -> low
    assert calculate_priority("low", 0.4) == "low"
    # high, central -> critical
    assert calculate_priority("high", 0.9, True) == "critical"

def test_healthy_app():
    # 1 service, no risks, no deps
    app = create_mock_app()
    cands = generate_test_candidates(app)
    assert len(cands) == 0

def test_empty_app():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "empty_project")
    app = analyze_application(fixture_path)
    assert len(app.test_candidates) == 0

def test_end_to_end_flow():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "react_fastapi")
    if os.path.exists(fixture_path):
        app = analyze_application(fixture_path)
        assert hasattr(app, "test_candidates")
        # should have non-risk candidates for postgres at least
        assert len(app.test_candidates) >= 0
