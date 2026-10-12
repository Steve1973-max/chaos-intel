import pytest
import json
import os
import subprocess
from datetime import datetime, timezone
from src.models.application import ApplicationModel
from src.models.technology import Technology
from src.models.service import Service
from src.models.dependency import Dependency
from src.models.api import Api
from src.models.architecture import ArchitectureGraph, GraphNode, GraphEdge
from src.models.risk import RiskFinding
from src.models.test_candidate import TestCandidate
from src.models.experiment import ExperimentSpecification, Target, Fault, BlastRadius, SteadyState, Rollback, Safety
from src.models.safety import SafetyDecision
from src.models.experiment_run import ExperimentRun
from src.reporting.report_builder import build_application_report
from src.reporting.json_reporter import generate_json_report
from src.reporting.markdown_reporter import generate_markdown_report, escape_md
from src.reporting.mermaid_reporter import generate_mermaid_report, escape_mermaid_label, sanitize_id
from src.reporting.models import ApplicationReport

@pytest.fixture
def empty_model():
    return ApplicationModel(application_id="app-123", name="EmptyApp")

@pytest.fixture
def populated_model():
    tech = Technology(name="Python", category="language", confidence=1.0, evidence=[])
    svc = Service(service_id="svc-1", application_id="app-123", name="backend", type="backend", technology="Python", source_path="/src")
    dep = Dependency(source_service_id="svc-1", dependency_type="database", name="db")
    api = Api(api_id="api-1", application_id="app-123", service_id="svc-1", path="/health", method="GET")
    
    node1 = GraphNode(node_id="n1", node_type="service", name="backend")
    node2 = GraphNode(node_id="n2", node_type="database", name="db")
    edge1 = GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n2", edge_type="calls")
    graph = ArchitectureGraph(nodes=[node1, node2], edges=[edge1])
    
    risk = RiskFinding(
        risk_id="r1", application_id="app-123", category="architecture", 
        risk_type="single_point_of_failure", severity="high", 
        title="DB SPOF", description="No replica", target_type="database", target_id="n2"
    )
    
    tc = TestCandidate(
        candidate_id="tc-1", application_id="app-123", target_type="database", target_id="n2",
        test_type="availability", title="Kill DB", hypothesis="App should fail gracefully",
        reason="Test SPOF", expected_failure_mode="degraded", priority="high"
    )
    
    exp = ExperimentSpecification(
        experiment_id="exp-1", application_id="app-123", candidate_ids=["tc-1"],
        name="Kill DB Exp", hypothesis="Fails gracefully", status="draft",
        target=Target(type="database", id="n2", name="db"),
        fault=Fault(type="pod_delete", method="chaosmesh"),
        duration_seconds=60, blast_radius=BlastRadius(scope="db", max_affected_components=1),
        steady_state=SteadyState(required=False), rollback=Rollback(strategy="auto", automatic=True),
        safety=Safety(requires_approval=True)
    )
    
    sd = SafetyDecision(
        decision_id="sd-1", experiment_id="exp-1", application_id="app-123",
        decision="approved", allowed=True
    )
    
    run = ExperimentRun(
        run_id="run-1", experiment_id="exp-1", application_id="app-123",
        safety_decision_id="sd-1", state="completed"
    )
    
    return ApplicationModel(
        application_id="app-123",
        name="PopulatedApp",
        technologies=[tech],
        services=[svc],
        dependencies=[dep],
        apis=[api],
        architecture=graph,
        risks=[risk],
        test_candidates=[tc],
        experiments=[exp],
        safety_decisions=[sd],
        experiment_runs=[run]
    )

def test_build_report_empty(empty_model):
    report = build_application_report(empty_model)
    assert report.application_id == "app-123"
    assert report.name == "EmptyApp"
    assert report.summaries.total_technologies == 0
    assert report.summaries.total_services == 0
    assert report.summaries.total_dependencies == 0
    assert report.summaries.total_apis == 0
    assert len(report.warnings) == 2  # No technologies, No services
    
    # Input immutability verification
    assert id(report.architecture) != id(empty_model.architecture)

def test_build_report_populated(populated_model):
    fixed_time = "2026-10-09T00:00:00Z"
    report = build_application_report(populated_model, generated_at=fixed_time)
    
    assert report.generated_at == fixed_time
    assert report.summaries.total_technologies == 1
    assert report.summaries.total_services == 1
    assert report.summaries.total_dependencies == 1
    assert report.summaries.total_apis == 1
    assert report.summaries.risks_by_severity.get("high") == 1
    assert report.summaries.test_candidates_by_type.get("availability") == 1
    assert report.summaries.test_candidates_by_priority.get("high") == 1
    assert report.summaries.experiments_by_fault_type.get("pod_delete") == 1
    assert report.summaries.safety_decisions_by_status.get("approved") == 1
    assert report.summaries.experiment_runs_by_state.get("completed") == 1
    
    assert len(report.warnings) == 0
    
    # Input immutability
    assert id(report.technologies) != id(populated_model.technologies)
    assert id(report.architecture) != id(populated_model.architecture)

def test_json_determinism(populated_model):
    fixed_time = "2026-10-09T00:00:00Z"
    report1 = build_application_report(populated_model, generated_at=fixed_time)
    report2 = build_application_report(populated_model, generated_at=fixed_time)
    
    json1 = generate_json_report(report1)
    json2 = generate_json_report(report2)
    
    assert json1 == json2
    assert fixed_time in json1
    
    # Validate it's valid JSON
    parsed = json.loads(json1)
    assert parsed["application_id"] == "app-123"
    assert parsed["name"] == "PopulatedApp"
    assert parsed["report_version"] == "1.0.0"

def test_markdown_determinism_and_escaping(populated_model):
    # Inject some markdown sensitive text
    populated_model.name = "App_Name_With_Underscores"
    populated_model.risks[0].title = "<script>alert(1)</script>"
    
    report = build_application_report(populated_model, generated_at="2026-10-09T00:00:00Z")
    md = generate_markdown_report(report)
    
    assert "\\_Name\\_With\\_Underscores" in md
    assert "\\<script\\>alert(1)\\</script\\>" in md
    
    # Ensure sections exist
    assert "## 1. Application Overview" in md
    assert "## 2. Technology Stack" in md
    assert "## 6. Risk Assessment" in md
    assert "## 7. Recommended Test Candidates" in md

def test_markdown_missing_optional_data(empty_model):
    report = build_application_report(empty_model)
    md = generate_markdown_report(report)
    
    assert "## 1. Application Overview" in md
    # Missing optional sections shouldn't be there
    assert "## 2. Technology Stack" not in md
    assert "## 3. Services and Dependencies" not in md
    assert "## 4. API Inventory" not in md
    assert "## 6. Risk Assessment" not in md
    assert "## Limitations and Warnings" in md

def test_mermaid_determinism(populated_model):
    report1 = build_application_report(populated_model)
    report2 = build_application_report(populated_model)
    
    mmd1 = generate_mermaid_report(report1)
    mmd2 = generate_mermaid_report(report2)
    
    assert mmd1 == mmd2
    assert "n_n1[\"backend\"]" in mmd1
    assert "n_n2[\"db\"]" in mmd1
    assert "n_n1 -->|\"calls\"| n_n2" in mmd1

def test_mermaid_empty_graph(empty_model):
    report = build_application_report(empty_model)
    mmd = generate_mermaid_report(report)
    assert "empty[\"Empty Architecture\"]" in mmd

def test_secret_redaction(populated_model):
    # Inject a secret into metadata
    populated_model.metadata = {"aws_access_key": "AKIAIOSFODNN7EXAMPLE", "public_info": "safe"}
    populated_model.services[0].metadata = {"DB_PASSWORD": "supersecretpassword"}
    
    report = build_application_report(populated_model)
    
    assert report.metadata.get("aws_access_key") == "***REDACTED***"
    assert report.metadata.get("public_info") == "safe"
    assert report.services[0].metadata.get("DB_PASSWORD") == "***REDACTED***"
    
    # Ensure JSON schema validation and serialization doesn't crash on redacted output
    json_out = generate_json_report(report)
    assert "supersecretpassword" not in json_out
    assert "AKIAIOSFODNN7EXAMPLE" not in json_out
    assert "***REDACTED***" in json_out
    mmd = generate_mermaid_report(report)
    assert "n_n1[\"backend\"]" in mmd

def test_mermaid_cyclic_graph():
    node1 = GraphNode(node_id="n1", node_type="service", name="A")
    node2 = GraphNode(node_id="n2", node_type="service", name="B")
    edge1 = GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n2", edge_type="calls")
    edge2 = GraphEdge(edge_id="e2", source_node_id="n2", target_node_id="n1", edge_type="callbacks")
    
    graph = ArchitectureGraph(nodes=[node1, node2], edges=[edge1, edge2])
    app = ApplicationModel(application_id="a1", name="A1", architecture=graph)
    report = build_application_report(app)
    
    mmd = generate_mermaid_report(report)
    assert "n_n1 -->|\"calls\"| n_n2" in mmd
    assert "n_n2 -->|\"callbacks\"| n_n1" in mmd

def test_mermaid_label_escaping():
    node = GraphNode(node_id="n1", node_type="service", name="A \"quoted\" name (test)")
    graph = ArchitectureGraph(nodes=[node], edges=[])
    app = ApplicationModel(application_id="a1", name="A1", architecture=graph)
    report = build_application_report(app)
    
    mmd = generate_mermaid_report(report)
    assert "A #quot;quoted#quot; name #40;test#41;" in mmd
    
def test_cli_output_json(populated_model, tmp_path):
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.json"
    
    # Write input file
    input_file.write_text(populated_model.model_dump_json(by_alias=True))
    
    # Run CLI
    result = subprocess.run(
        ["python", "-m", "src.main", "report", "--input", str(input_file), "--format", "json", "--output", str(output_file)],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    
    assert result.returncode == 0
    assert output_file.exists()
    
    out_data = json.loads(output_file.read_text(encoding="utf-8"))
    assert out_data["application_id"] == "app-123"

def test_cli_output_markdown(populated_model, tmp_path):
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.md"
    
    input_file.write_text(populated_model.model_dump_json(by_alias=True))
    
    result = subprocess.run(
        ["python", "-m", "src.main", "report", "--input", str(input_file), "--format", "markdown", "--output", str(output_file)],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    
    assert result.returncode == 0
    assert output_file.exists()
    assert "# CHAOS-INTEL Application Assessment:" in output_file.read_text(encoding="utf-8")

def test_cli_output_mermaid(populated_model, tmp_path):
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.mmd"
    
    input_file.write_text(populated_model.model_dump_json(by_alias=True))
    
    result = subprocess.run(
        ["python", "-m", "src.main", "report", "--input", str(input_file), "--format", "mermaid", "--output", str(output_file)],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    
    assert result.returncode == 0
    assert output_file.exists()
    assert "graph TD" in output_file.read_text(encoding="utf-8")

def test_cli_overwrite_protection(populated_model, tmp_path):
    input_file = tmp_path / "input.json"
    input_file.write_text(populated_model.model_dump_json(by_alias=True))
    
    result = subprocess.run(
        ["python", "-m", "src.main", "report", "--input", str(input_file), "--format", "json", "--output", str(input_file)],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    
    assert result.returncode != 0
    assert "Error: Output file path" in result.stderr

def test_cli_invalid_input(tmp_path):
    input_file = tmp_path / "input.json"
    input_file.write_text('{"invalid": "json"') # malformed json
    output_file = tmp_path / "output.json"
    
    result = subprocess.run(
        ["python", "-m", "src.main", "report", "--input", str(input_file), "--format", "json", "--output", str(output_file)],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    
    assert result.returncode != 0
    assert "Error reading or validating input model" in result.stderr
    assert not output_file.exists()
