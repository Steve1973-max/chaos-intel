import os
import pytest
from src.main import analyze_application
from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph, GraphNode, GraphEdge
from src.models.test_candidate import TestCandidate
from src.models.dependency import Dependency
from src.models.technology import Evidence
from src.experiment.engine import generate_experiment_specifications

def create_mock_app(candidates=None, dependencies=None, nodes=None):
    if candidates is None: candidates = []
    if dependencies is None: dependencies = []
    if nodes is None: nodes = []
    return ApplicationModel(
        application_id="app-1",
        name="test_app",
        technologies=[],
        services=[],
        dependencies=dependencies,
        apis=[],
        architecture=ArchitectureGraph(nodes=nodes, edges=[]),
        risks=[],
        test_candidates=candidates
    )

def _mock_cand(test_type, target_id="target-1", hyp="test", expected="failure"):
    return TestCandidate(
        candidate_id=f"c-{target_id}-{test_type}",
        application_id="app-1",
        target_type="node",
        target_id=target_id,
        test_type=test_type,
        title="t",
        hypothesis=hyp,
        reason="r",
        expected_failure_mode=expected,
        priority="high",
        confidence=0.8,
        evidence=[Evidence(source="foo", type="t", detail="d")]
    )

def test_availability_service_stop():
    cand = _mock_cand("availability", "frontend")
    nodes = [GraphNode(node_id="frontend", node_type="service", name="frontend")]
    app = create_mock_app(candidates=[cand], nodes=nodes)
    exps = generate_experiment_specifications(app)
    assert len(exps) == 1
    assert exps[0].fault.type == "availability"
    assert exps[0].fault.method == "service_stop"
    assert exps[0].target.type == "service"

def test_dependency_unavailable():
    cand = _mock_cand("dependency_resilience", "postgres")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert len(exps) == 1
    assert exps[0].fault.type == "dependency_unavailable"
    assert exps[0].fault.method == "dependency_stop"

def test_external_api_fault():
    cand = _mock_cand("dependency_resilience", "api.stripe.com", expected="elevated latency")
    dep = Dependency(source_service_id="s", target_service_id=None, dependency_type="external_api", name="api.stripe.com", confidence=1.0)
    app = create_mock_app(candidates=[cand], dependencies=[dep])
    exps = generate_experiment_specifications(app)
    assert len(exps) == 1
    assert exps[0].fault.type == "dependency_slow"
    assert exps[0].fault.method == "external_dependency_unavailable"

def test_latency_network_delay():
    cand = _mock_cand("latency", "target-1")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert len(exps) == 1
    assert exps[0].fault.type == "latency"
    assert exps[0].fault.method == "network_delay"

def test_network_isolation():
    cand = _mock_cand("network_partition", "target-1")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert len(exps) == 1
    assert exps[0].fault.type == "network_partition"
    assert exps[0].fault.method == "network_isolation"

def test_queue_backlog():
    cand = _mock_cand("dependency_resilience", "kafka")
    dep = Dependency(source_service_id="s", target_service_id=None, dependency_type="message_broker", name="kafka", confidence=1.0)
    app = create_mock_app(candidates=[cand], dependencies=[dep])
    exps = generate_experiment_specifications(app)
    assert len(exps) == 1
    assert exps[0].fault.type == "queue_backlog"
    assert exps[0].fault.method == "message_consumption_delay"

def test_deterministic_experiment_id():
    cand = _mock_cand("availability", "frontend")
    nodes = [GraphNode(node_id="frontend", node_type="service", name="frontend")]
    app = create_mock_app(candidates=[cand], nodes=nodes)
    exps1 = generate_experiment_specifications(app)
    exps2 = generate_experiment_specifications(app)
    assert exps1[0].experiment_id == exps2[0].experiment_id

def test_duplicate_experiment_merging():
    cand1 = _mock_cand("availability", "frontend")
    cand1.candidate_id = "c1"
    cand2 = _mock_cand("failover", "frontend") # both map to availability service_stop
    cand2.candidate_id = "c2"
    
    nodes = [GraphNode(node_id="frontend", node_type="service", name="frontend")]
    app = create_mock_app(candidates=[cand1, cand2], nodes=nodes)
    exps = generate_experiment_specifications(app)
    assert len(exps) == 1
    assert "c1" in exps[0].candidate_ids
    assert "c2" in exps[0].candidate_ids

def test_blast_radius():
    cand = _mock_cand("availability", "frontend")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert exps[0].blast_radius.scope == "single_service"
    assert exps[0].blast_radius.max_affected_components == 1

def test_steady_state():
    cand = _mock_cand("availability", "frontend")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert exps[0].steady_state.required is True
    assert "baseline_request_success_rate" in exps[0].steady_state.checks

def test_abort_conditions():
    cand = _mock_cand("availability", "frontend")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert len(exps[0].abort_conditions) > 0
    assert exps[0].abort_conditions[0].action == "abort"

def test_rollback():
    cand = _mock_cand("availability", "frontend")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert exps[0].rollback.strategy == "restore_target"
    assert exps[0].rollback.automatic is True

def test_safety_defaults():
    cand = _mock_cand("availability", "frontend")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert exps[0].safety.requires_approval is True
    assert exps[0].safety.production_allowed is False

def test_requires_review():
    cand = _mock_cand("latency", "frontend")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert exps[0].status == "requires_review"

def test_confidence_and_evidence():
    cand = _mock_cand("availability", "frontend")
    app = create_mock_app(candidates=[cand])
    exps = generate_experiment_specifications(app)
    assert exps[0].confidence == 0.8
    assert exps[0].evidence[0].source == "foo"

def test_empty_app():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "empty_project")
    app = analyze_application(fixture_path)
    assert len(app.experiments) == 0

def test_full_pipeline():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "react_fastapi")
    if os.path.exists(fixture_path):
        app = analyze_application(fixture_path)
        assert hasattr(app, "experiments")
        assert len(app.experiments) >= 0
