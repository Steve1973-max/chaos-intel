import os
import pytest
import json
from src.main import analyze_application
from src.models.architecture import ArchitectureGraph
from src.models.service import Service
from src.models.dependency import Dependency
from src.models.technology import Technology, Evidence
from src.graph.graph_builder import build_architecture_graph

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def test_simple_monolith():
    fixture_path = os.path.join(FIXTURES_DIR, "python_fastapi")
    app = analyze_application(fixture_path)
    
    assert app.name == "python_fastapi"
    assert app.application_id.startswith("app-")
    
    # Python FastAPI is a monolith without dependencies in that simple fixture
    assert len(app.services) == 1
    assert app.services[0].name == "monolith" # the detector defaults to monolith if it can't find specific name
    
    # Graph should have 1 node and 0 edges
    assert len(app.architecture.nodes) == 1
    assert len(app.architecture.edges) == 0
    assert app.architecture.nodes[0].name == "monolith"

def test_frontend_backend_postgres():
    services = [
        Service(service_id="svc-1", application_id="app", name="frontend", type="frontend", source_path="frontend"),
        Service(service_id="svc-2", application_id="app", name="backend", type="backend", source_path="backend"),
    ]
    dependencies = [
        Dependency(source_service_id="svc-1", target_service_id="svc-2", dependency_type="http", name="backend", confidence=1.0),
        Dependency(source_service_id="svc-2", target_service_id=None, dependency_type="postgres", name="db", confidence=1.0)
    ]
    
    graph = build_architecture_graph(services, dependencies, [], [])
    node_ids = set([n.node_id for n in graph.nodes])
    assert len(node_ids) == len(graph.nodes)
    
    node_names = {n.name for n in graph.nodes}
    assert "frontend" in node_names
    assert "backend" in node_names
    assert "db" in node_names
    
    edges = graph.edges
    assert len(edges) == 2
    
    fe_node = next(n for n in graph.nodes if n.name == "frontend")
    be_node = next(n for n in graph.nodes if n.name == "backend")
    db_node = next(n for n in graph.nodes if n.name == "db")
    
    assert any(e.source_node_id == fe_node.node_id and e.target_node_id == be_node.node_id for e in edges)
    assert any(e.source_node_id == be_node.node_id and e.target_node_id == db_node.node_id for e in edges)

def test_external_api():
    services = [
        Service(service_id="svc-1", application_id="app", name="backend", type="backend", source_path="backend")
    ]
    dependencies = [
        Dependency(source_service_id="svc-1", target_service_id=None, dependency_type="external_api", name="https://api.stripe.com/v1/charges", confidence=1.0)
    ]
    graph = build_architecture_graph(services, dependencies, [], [])
    
    node_names = {n.name for n in graph.nodes}
    assert "api.stripe.com" in node_names
    
    stripe_node = next(n for n in graph.nodes if n.name == "api.stripe.com")
    assert stripe_node.node_type == "external_service"

def test_technology_only():
    # If we have technology but no dependency, it shouldn't create a node
    services = [
        Service(service_id="svc-1", application_id="app", name="backend", type="backend", source_path="backend")
    ]
    technologies = [
        Technology(name="React", category="frontend", confidence=1.0, evidence=[Evidence(source="backend/package.json", type="file", detail="react")])
    ]
    graph = build_architecture_graph(services, [], [], technologies)
    
    node_names = {n.name for n in graph.nodes}
    assert "React" not in node_names
    assert "backend" in node_names
    assert "React" in graph.nodes[0].technology_references

def test_duplicate_edges():
    services = [
        Service(service_id="svc-1", application_id="app", name="frontend", type="frontend", source_path="frontend"),
        Service(service_id="svc-2", application_id="app", name="backend", type="backend", source_path="backend"),
    ]
    dependencies = [
        Dependency(source_service_id="svc-1", target_service_id="svc-2", dependency_type="http", name="backend", confidence=1.0, evidence=[Evidence(source="f1", type="t1", detail="d1")]),
        Dependency(source_service_id="svc-1", target_service_id="svc-2", dependency_type="http", name="backend", confidence=1.0, evidence=[Evidence(source="f2", type="t2", detail="d2")])
    ]
    graph = build_architecture_graph(services, dependencies, [], [])
    assert len(graph.edges) == 1
    assert len(graph.edges[0].evidence) == 2

def test_empty_application():
    fixture_path = os.path.join(FIXTURES_DIR, "empty_project")
    if not os.path.exists(fixture_path):
        os.makedirs(fixture_path, exist_ok=True)
    app = analyze_application(fixture_path)
    assert len(app.architecture.nodes) == 0
    assert len(app.architecture.edges) == 0

def test_graph_validation():
    fixture_path = os.path.join(FIXTURES_DIR, "react_fastapi")
    app = analyze_application(fixture_path)
    assert "graph_validation_errors" not in app.metadata.get("diagnostics", {})
    
    from src.graph.graph_serializer import serialize_graph
    json_str = serialize_graph(app.architecture)
    data = json.loads(json_str)
    assert "nodes" in data
    assert "edges" in data

def test_cyclic_services():
    from src.graph.graph_validator import validate_graph
    from src.models.architecture import GraphNode, GraphEdge
    graph = ArchitectureGraph(
        nodes=[
            GraphNode(node_id="n1", node_type="service", name="A"),
            GraphNode(node_id="n2", node_type="service", name="B"),
            GraphNode(node_id="n3", node_type="service", name="C"),
        ],
        edges=[
            GraphEdge(edge_id="e1", source_node_id="n1", target_node_id="n2", edge_type="http"),
            GraphEdge(edge_id="e2", source_node_id="n2", target_node_id="n3", edge_type="http"),
            GraphEdge(edge_id="e3", source_node_id="n3", target_node_id="n1", edge_type="http"),
        ]
    )
    errors = validate_graph(graph)
    assert not errors
