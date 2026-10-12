import os
import pytest
from src.detectors.service_detector import discover_services

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def test_monolith_fastapi():
    fixture_path = os.path.join(FIXTURES_DIR, "monolith_fastapi")
    services = discover_services(fixture_path)
    
    # Internal directories like models/, services/, utils/ should not be services.
    # We just expect 1 fallback monolith service here since there's no compose or manifest.
    assert len(services) == 1
    assert services[0].name == "monolith"
    assert services[0].type == "unknown"

def test_docker_microservices():
    fixture_path = os.path.join(FIXTURES_DIR, "docker_microservices")
    services = discover_services(fixture_path)
    
    assert len(services) == 5
    svc_names = {s.name: s for s in services}
    assert "frontend" in svc_names
    assert "backend" in svc_names
    assert "worker" in svc_names
    assert "postgres" in svc_names
    assert "redis" in svc_names
    
    assert svc_names["frontend"].type == "frontend"
    assert svc_names["backend"].type == "backend"
    assert svc_names["worker"].type == "worker"
    assert svc_names["postgres"].type == "database"
    assert svc_names["redis"].type == "cache"

def test_kubernetes_basic():
    fixture_path = os.path.join(FIXTURES_DIR, "kubernetes_basic")
    services = discover_services(fixture_path)
    
    assert len(services) == 1
    assert services[0].name == "payment-service"
    assert services[0].source_path == "kubernetes"

def test_empty_project():
    fixture_path = os.path.join(FIXTURES_DIR, "empty_project")
    services = discover_services(fixture_path)
    assert len(services) == 0
