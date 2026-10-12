import os
import pytest
from src.detectors.technology_detector import analyze_application

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def test_react_fastapi_fixture():
    fixture_path = os.path.join(FIXTURES_DIR, "react_fastapi")
    inventory = analyze_application(fixture_path)
    
    techs = {t.name: t for t in inventory.technologies}
    
    assert "React" in techs
    assert techs["React"].version == "^18.3.1"
    assert techs["React"].confidence >= 0.8
    assert techs["React"].category == "frontend"
    
    assert "FastAPI" in techs
    assert techs["FastAPI"].version == "0.115.0"
    assert techs["FastAPI"].confidence >= 0.8
    assert techs["FastAPI"].category == "backend"

    assert "Docker Compose" in techs
    assert techs["Docker Compose"].confidence >= 0.4
    assert techs["Docker Compose"].category == "infrastructure"

    assert "TypeScript" in techs
    assert techs["TypeScript"].confidence >= 0.8
    
    assert "PostgreSQL" in techs
    assert techs["PostgreSQL"].version == "2.9.9"

def test_node_express_fixture():
    fixture_path = os.path.join(FIXTURES_DIR, "node_express")
    inventory = analyze_application(fixture_path)
    
    techs = {t.name: t for t in inventory.technologies}
    
    assert "Express" in techs
    assert techs["Express"].version == "^4.18.2"
    
    assert "MongoDB" in techs
    assert techs["MongoDB"].version == "^7.0.0"

    assert "JavaScript" in techs
    assert techs["JavaScript"].confidence > 0.3

def test_python_fastapi_fixture():
    fixture_path = os.path.join(FIXTURES_DIR, "python_fastapi")
    inventory = analyze_application(fixture_path)
    
    techs = {t.name: t for t in inventory.technologies}
    
    assert "FastAPI" in techs
    assert techs["FastAPI"].version is None
    
    assert "Python" in techs
    assert techs["Python"].confidence > 0.3

def test_empty_project_behavior():
    import tempfile
    with tempfile.TemporaryDirectory() as tempdir:
        inventory = analyze_application(tempdir)
        assert len(inventory.technologies) == 0

def test_invalid_path():
    inventory = analyze_application("/invalid/path/that/does/not/exist")
    assert len(inventory.technologies) == 0
