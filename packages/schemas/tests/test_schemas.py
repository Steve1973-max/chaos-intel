import json
import os
import pytest
import jsonschema
from referencing import Registry, Resource

SCHEMA_DIR = os.path.dirname(os.path.dirname(__file__))

def load_schema(filename):
    path = os.path.join(SCHEMA_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)

def create_registry():
    schemas = [
        "dependency.schema.json",
        "service.schema.json",
        "application.schema.json",
        "architecture.schema.json",
        "test-candidate.schema.json",
        "experiment-candidate.schema.json",
        "test-run.schema.json",
        "experiment.schema.json",
        "experiment-run.schema.json",
        "finding.schema.json",
        "recommendation.schema.json"
    ]
    registry = Registry()
    for filename in schemas:
        schema = load_schema(filename)
        resource = Resource.from_contents(schema)
        if "$id" in schema:
            registry = registry.with_resource(uri=schema["$id"], resource=resource)
        registry = registry.with_resource(uri=filename, resource=resource)
    return registry

registry = create_registry()

def test_dependency_schema():
    schema = load_schema("dependency.schema.json")
    jsonschema.Draft7Validator.check_schema(schema)
    valid_instance = {
        "source_service_id": "svc-frontend",
        "target_service_id": "svc-backend",
        "dependency_type": "http",
        "name": "backend",
        "evidence": [
            {"source": "docker-compose.yml", "type": "config", "detail": "depends_on: backend"}
        ]
    }
    validator = jsonschema.Draft7Validator(schema, registry=registry)
    validator.validate(valid_instance)

def test_service_schema():
    schema = load_schema("service.schema.json")
    jsonschema.Draft7Validator.check_schema(schema)
    valid_instance = {
        "service_id": "svc-123",
        "application_id": "app-001",
        "name": "Frontend",
        "type": "frontend",
        "source_path": "apps/web",
        "technology": "React",
        "entry_points": [],
        "ports": [8080],
        "confidence": 0.95,
        "evidence": []
    }
    validator = jsonschema.Draft7Validator(schema, registry=registry)
    validator.validate(valid_instance)

def test_application_schema():
    schema = load_schema("application.schema.json")
    jsonschema.Draft7Validator.check_schema(schema)
    valid_instance = {
        "id": "app-001",
        "name": "ChaosIntelWebApp",
        "repository_url": "https://github.com/chaos/intel",
        "technologies": [
            {
                "name": "React",
                "confidence": 0.99,
                "evidence": "package.json",
                "source": "dependency",
                "reasoning": "react dependency detected"
            }
        ],
        "services": [],
        "dependencies": [],
        "architecture": {
            "application_id": "app-001",
            "nodes": [],
            "edges": []
        },
        "metadata": {"ingestion_source": "github_actions"}
    }
    validator = jsonschema.Draft7Validator(schema, registry=registry)
    validator.validate(valid_instance)

def test_architecture_schema():
    schema = load_schema("architecture.schema.json")
    jsonschema.Draft7Validator.check_schema(schema)
    valid_instance = {
        "application_id": "app-001",
        "nodes": [
            {"node_id": "node-1", "node_type": "service", "name": "Frontend", "confidence": 1.0, "evidence": []}
        ],
        "edges": []
    }
    validator = jsonschema.Draft7Validator(schema, registry=registry)
    validator.validate(valid_instance)

def test_placeholder_schemas():
    placeholders = [
        "test-candidate.schema.json",
        "experiment-candidate.schema.json",
        "test-run.schema.json",
        "experiment.schema.json",
        "experiment-run.schema.json",
        "finding.schema.json",
        "recommendation.schema.json"
    ]
    for filename in placeholders:
        schema = load_schema(filename)
        jsonschema.Draft7Validator.check_schema(schema)
        assert "description" in schema
