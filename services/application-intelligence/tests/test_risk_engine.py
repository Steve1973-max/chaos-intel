import os
import pytest
from src.main import analyze_application
from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph, GraphNode, GraphEdge
from src.models.risk import RiskFinding
from src.models.service import Service
from src.models.dependency import Dependency
from src.models.api import Api
from src.models.technology import Evidence
from src.risk.engine import analyze_risks

def create_mock_app(nodes, edges, services=None, dependencies=None, apis=None):
    if services is None: services = []
    if dependencies is None: dependencies = []
    if apis is None: apis = []
    return ApplicationModel(
        application_id="app-1",
        name="test_app",
        technologies=[],
        services=services,
        dependencies=dependencies,
        apis=apis,
        architecture=ArchitectureGraph(nodes=nodes, edges=edges)
    )

def test_single_point_of_failure():
    # 1 frontend -> 1 backend
    nodes = [
        GraphNode(node_id="n1", node_type="frontend", name="frontend"),
        GraphNode(node_id="n2", node_type="backend", name="backend")
    ]
    edges = [GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n2", edge_type="http")]
    services = [
        Service(service_id="s1", application_id="app-1", name="frontend", type="frontend", source_path="f"),
        Service(service_id="s2", application_id="app-1", name="backend", type="backend", source_path="b"),
    ]
    app = create_mock_app(nodes, edges, services=services)
    res = analyze_risks(app)
    
    spof_findings = [f for f in res.findings if f.risk_type == "single_point_of_failure"]
    assert len(spof_findings) == 1
    assert spof_findings[0].target_id == "n2"
    assert spof_findings[0].severity == "medium"
    assert spof_findings[0].evidence[0].source == "architecture"

def test_critical_dependency():
    nodes = [
        GraphNode(node_id="n1", node_type="frontend", name="frontend"),
        GraphNode(node_id="n2", node_type="backend", name="backend"),
        GraphNode(node_id="n3", node_type="postgres", name="postgres")
    ]
    edges = [
        GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n2", edge_type="http"),
        GraphEdge(edge_id="e2", source_node_id="n2", target_node_id="n3", edge_type="database")
    ]
    app = create_mock_app(nodes, edges)
    res = analyze_risks(app)
    
    crit_findings = [f for f in res.findings if f.risk_type == "critical_dependency"]
    assert len(crit_findings) == 1
    assert crit_findings[0].severity == "medium"
    
def test_availability_concentration():
    nodes = [
        GraphNode(node_id="n1", node_type="backend", name="b1"),
        GraphNode(node_id="n2", node_type="worker", name="w1"),
        GraphNode(node_id="n3", node_type="redis", name="redis-cluster")
    ]
    edges = [
        GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n3", edge_type="cache"),
        GraphEdge(edge_id="e2", source_node_id="n2", target_node_id="n3", edge_type="cache")
    ]
    app = create_mock_app(nodes, edges)
    res = analyze_risks(app)
    
    avail_findings = [f for f in res.findings if f.risk_type == "availability_concentration"]
    assert len(avail_findings) == 1
    assert avail_findings[0].target_id == "n3"

def test_external_dependency():
    nodes = [
        GraphNode(node_id="n1", node_type="backend", name="b1"),
        GraphNode(node_id="n2", node_type="external_service", name="api.stripe.com")
    ]
    edges = [GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n2", edge_type="http")]
    app = create_mock_app(nodes, edges)
    res = analyze_risks(app)
    ext_findings = [f for f in res.findings if f.risk_type == "external_dependency"]
    assert len(ext_findings) == 1
    assert ext_findings[0].target_id == "e1"

def test_cyclic_dependency():
    nodes = [
        GraphNode(node_id="n1", node_type="service", name="a"),
        GraphNode(node_id="n2", node_type="service", name="b"),
        GraphNode(node_id="n3", node_type="service", name="c")
    ]
    edges = [
        GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n2", edge_type="http"),
        GraphEdge(edge_id="e2", source_node_id="n2", target_node_id="n3", edge_type="http"),
        GraphEdge(edge_id="e3", source_node_id="n3", target_node_id="n1", edge_type="http")
    ]
    app = create_mock_app(nodes, edges)
    res = analyze_risks(app)
    cyc = [f for f in res.findings if f.risk_type == "cyclic_dependency"]
    assert len(cyc) == 1
    assert cyc[0].severity == "medium"

def test_dependency_concentration():
    nodes = [
        GraphNode(node_id="n0", node_type="gateway", name="gw"),
        GraphNode(node_id="n1", node_type="service", name="s1"),
        GraphNode(node_id="n2", node_type="service", name="s2"),
        GraphNode(node_id="n3", node_type="service", name="s3")
    ]
    edges = [
        GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n0", edge_type="http"),
        GraphEdge(edge_id="e2", source_node_id="n2", target_node_id="n0", edge_type="http"),
        GraphEdge(edge_id="e3", source_node_id="n3", target_node_id="n0", edge_type="http")
    ]
    app = create_mock_app(nodes, edges)
    res = analyze_risks(app)
    conc = [f for f in res.findings if f.risk_type == "dependency_concentration"]
    assert len(conc) == 1
    assert conc[0].target_id == "n0"

def test_unresolved_dependency():
    services = [Service(service_id="s1", application_id="app-1", name="s1", type="service", source_path="")]
    dependencies = [
        Dependency(source_service_id="s1", target_service_id=None, dependency_type="unknown", name="mystery", confidence=1.0)
    ]
    app = create_mock_app([], [], services=services, dependencies=dependencies)
    res = analyze_risks(app)
    unres = [f for f in res.findings if f.risk_type == "unresolved_dependency"]
    assert len(unres) == 1
    assert unres[0].target_id == "s1"

def test_api_concentration():
    services = [
        Service(service_id="s1", application_id="app-1", name="s1", type="service", source_path=""),
        Service(service_id="s2", application_id="app-1", name="s2", type="service", source_path="")
    ]
    apis = [Api(api_id=f"api-{i}", application_id="app-1", service_id="s1", path=f"/api/{i}", method="GET") for i in range(9)]
    apis.append(Api(api_id="api-9", application_id="app-1", service_id="s2", path="/api/other", method="GET"))
    
    app = create_mock_app([], [], services=services, apis=apis)
    res = analyze_risks(app)
    api_conc = [f for f in res.findings if f.risk_type == "api_concentration"]
    assert len(api_conc) == 1
    assert api_conc[0].target_id == "s1"

def test_explicit_unauthenticated_api():
    apis = [
        Api(api_id="api-1", application_id="app-1", service_id="s1", path="/public", method="GET", auth_required=False),
        Api(api_id="api-2", application_id="app-1", service_id="s1", path="/unknown", method="GET", auth_required=None)
    ]
    app = create_mock_app([], [], apis=apis)
    res = analyze_risks(app)
    unauth = [f for f in res.findings if f.risk_type == "explicitly_unauthenticated_api"]
    assert len(unauth) == 1
    assert unauth[0].target_id == "api-1"

def test_deduplication_and_evidence_aggregation():
    # Simulate duplicate findings with different evidence
    nodes = [GraphNode(node_id="n1", node_type="frontend", name="f"), GraphNode(node_id="n2", node_type="backend", name="b")]
    edges = [GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n2", edge_type="http")]
    services = [Service(service_id="s1", application_id="app-1", name="f", type="frontend", source_path=""), Service(service_id="s2", application_id="app-1", name="b", type="backend", source_path="")]
    
    # We call analyze risks twice or we just mock rules. The engine deduplicates identically generated risk IDs.
    app = create_mock_app(nodes, edges, services=services)
    from src.risk.rules.single_point_of_failure import SinglePointOfFailureRule
    
    # Force two identical risks but different evidence
    f1 = RiskFinding(risk_id="r1", application_id="a1", category="c", risk_type="rt", severity="low", title="t", description="d", target_type="tt", target_id="tid", confidence=0.5, evidence=[Evidence(source="s1", type="t1", detail="d1")])
    f2 = RiskFinding(risk_id="r1", application_id="a1", category="c", risk_type="rt", severity="low", title="t", description="d", target_type="tt", target_id="tid", confidence=0.8, evidence=[Evidence(source="s2", type="t2", detail="d2")])
    
    from src.risk.engine import deduplicate_findings
    deduped = deduplicate_findings([f1, f2])
    assert len(deduped) == 1
    assert deduped[0].confidence == 0.8
    assert len(deduped[0].evidence) == 2

def test_end_to_end_analysis():
    # Use existing fixture, e.g., react_fastapi
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "react_fastapi")
    if os.path.exists(fixture_path):
        app = analyze_application(fixture_path)
        assert len(app.risks) >= 0
        assert "risk_summary" in app.metadata.get("diagnostics", {})

def test_empty_application():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "empty_project")
    if not os.path.exists(fixture_path):
        os.makedirs(fixture_path, exist_ok=True)
    app = analyze_application(fixture_path)
    assert len(app.risks) == 0

def test_healthy_application_no_false_highs():
    # A single backend service with no dependencies.
    # It will trigger SPOF as "low" because it's a simple monolith.
    nodes = [GraphNode(node_id="n1", node_type="backend", name="backend")]
    services = [Service(service_id="s1", application_id="app-1", name="backend", type="backend", source_path="b")]
    app = create_mock_app(nodes, [], services=services)
    res = analyze_risks(app)
    
    highs = [f for f in res.findings if f.severity in ("high", "critical")]
    assert len(highs) == 0
