import os
import pytest
from src.detectors.service_detector import discover_services
from src.detectors.dependency_detector import discover_dependencies

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def test_docker_microservices_dependencies():
    fixture_path = os.path.join(FIXTURES_DIR, "docker_microservices")
    services = discover_services(fixture_path)
    deps = discover_dependencies(fixture_path, services)
    
    # frontend -> backend
    frontend_deps = [d for d in deps if d.source_service_id == next(s.service_id for s in services if s.name == "frontend")]
    assert len(frontend_deps) == 1
    assert frontend_deps[0].name == "backend"
    assert frontend_deps[0].dependency_type == "http"
    
    # backend -> postgres, redis
    backend_deps = [d for d in deps if d.source_service_id == next(s.service_id for s in services if s.name == "backend")]
    assert len(backend_deps) == 2
    target_names = [d.name for d in backend_deps]
    assert "postgres" in target_names
    assert "redis" in target_names

def test_frontend_backend_dependencies():
    fixture_path = os.path.join(FIXTURES_DIR, "frontend_backend")
    services = discover_services(fixture_path)
    deps = discover_dependencies(fixture_path, services)
    
    assert len(deps) == 1
    assert deps[0].name == "backend"
    assert deps[0].dependency_type == "http"

def test_external_api_dependencies():
    fixture_path = os.path.join(FIXTURES_DIR, "external_api")
    services = discover_services(fixture_path)
    deps = discover_dependencies(fixture_path, services)
    
    assert len(deps) == 1
    assert deps[0].name == "api.stripe.com"
    assert deps[0].dependency_type == "http"

def test_secrets_fixture():
    fixture_path = os.path.join(FIXTURES_DIR, "secrets_fixture")
    services = discover_services(fixture_path)
    deps = discover_dependencies(fixture_path, services)
    
    assert len(deps) == 1
    assert deps[0].name == "db"
    assert deps[0].dependency_type == "database"
    
    # Check that secrets are not exposed
    ev_detail = deps[0].evidence[0].detail
    assert "DATABASE_URL" in ev_detail
    assert "supersecretpassword123!" not in ev_detail
    
    # Stripe key should be completely ignored (not a URL, not a supported dep)
    assert not any("STRIPE_KEY" in e.detail for d in deps for e in d.evidence)

def test_duplicate_evidence():
    fixture_path = os.path.join(FIXTURES_DIR, "duplicate_evidence")
    services = discover_services(fixture_path)
    deps = discover_dependencies(fixture_path, services)
    
    assert len(deps) == 1
    # DB dependency found via docker-compose and .env
    assert len(deps[0].evidence) == 2
    
    # One config evidence, one compose evidence
    types = {e.type for e in deps[0].evidence}
    assert "configuration" in types
    assert "docker_compose" in types
