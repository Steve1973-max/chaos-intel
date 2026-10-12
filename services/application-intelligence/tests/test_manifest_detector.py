import os
from src.detectors.manifest_detector import detect_dependencies_in_file

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def test_parse_package_json():
    filepath = os.path.join(FIXTURES_DIR, "react_fastapi", "frontend", "package.json")
    deps = detect_dependencies_in_file(filepath)
    assert "react" in deps
    assert deps["react"] == "^18.3.1"
    assert "typescript" in deps

def test_parse_requirements_txt():
    filepath = os.path.join(FIXTURES_DIR, "react_fastapi", "backend", "requirements.txt")
    deps = detect_dependencies_in_file(filepath)
    assert "fastapi" in deps
    assert deps["fastapi"] == "0.115.0"
    assert "psycopg2-binary" in deps
    assert deps["psycopg2-binary"] == "2.9.9"

def test_parse_requirements_no_version():
    filepath = os.path.join(FIXTURES_DIR, "python_fastapi", "requirements.txt")
    deps = detect_dependencies_in_file(filepath)
    assert "fastapi" in deps
    assert deps["fastapi"] is None

def test_invalid_manifest():
    deps = detect_dependencies_in_file("does_not_exist.json")
    assert deps == {}
