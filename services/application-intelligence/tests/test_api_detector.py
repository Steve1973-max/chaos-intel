import os
import pytest
from src.main import analyze_services_and_dependencies

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def test_fastapi_routes():
    fixture_path = os.path.join(FIXTURES_DIR, "fastapi_routes")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 3
    
    methods_paths = {(api.method, api.path) for api in result.apis}
    assert ("GET", "/users") in methods_paths
    assert ("POST", "/users") in methods_paths
    assert ("GET", "/api/v1/items/{id}") in methods_paths

def test_flask_routes():
    fixture_path = os.path.join(FIXTURES_DIR, "flask_routes")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 3 # GET /users, GET /items/{item_id}, DELETE /items/{item_id}
    
    methods_paths = {(api.method, api.path) for api in result.apis}
    assert ("GET", "/users") in methods_paths
    assert ("GET", "/items/{item_id}") in methods_paths
    assert ("DELETE", "/items/{item_id}") in methods_paths

def test_django_routes():
    fixture_path = os.path.join(FIXTURES_DIR, "django_routes")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 3
    paths = {api.path for api in result.apis}
    assert "/users" in paths
    assert "/items/{id}" in paths
    assert "/articles/{year}" in paths

def test_express_routes():
    fixture_path = os.path.join(FIXTURES_DIR, "express_routes")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 3
    methods_paths = {(api.method, api.path) for api in result.apis}
    assert ("GET", "/health") in methods_paths
    assert ("POST", "/api/create") in methods_paths
    assert ("GET", "/api/:id") in methods_paths

def test_nestjs_routes():
    fixture_path = os.path.join(FIXTURES_DIR, "nestjs_routes")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 2
    methods_paths = {(api.method, api.path) for api in result.apis}
    assert ("GET", "/cats") in methods_paths
    assert ("POST", "/cats/:id") in methods_paths

def test_spring_routes():
    fixture_path = os.path.join(FIXTURES_DIR, "spring_routes")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 2
    methods_paths = {(api.method, api.path) for api in result.apis}
    assert ("GET", "/api/products") in methods_paths
    assert ("POST", "/api/products/{id}") in methods_paths

def test_aspnet_routes():
    fixture_path = os.path.join(FIXTURES_DIR, "aspnet_routes")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 2
    methods_paths = {(api.method, api.path) for api in result.apis}
    assert ("GET", "/api/weatherforecast") in methods_paths
    assert ("POST", "/api/weatherforecast/{id}") in methods_paths

def test_openapi_spec():
    fixture_path = os.path.join(FIXTURES_DIR, "openapi_spec")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 3
    api_map = {(api.method, api.path): api for api in result.apis}
    
    assert ("GET", "/orders") in api_map
    assert ("POST", "/orders") in api_map
    assert ("GET", "/orders/{id}") in api_map
    
    post_order = api_map[("POST", "/orders")]
    assert post_order.auth_required is True
    
    get_orders = api_map[("GET", "/orders")]
    assert get_orders.auth_required is True # Inherits from global security
    
    assert len(get_orders.parameters) == 1
    assert get_orders.parameters[0].name == "status"

def test_duplicate_endpoint():
    fixture_path = os.path.join(FIXTURES_DIR, "duplicate_endpoint")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 1
    api = result.apis[0]
    assert api.method == "GET"
    assert api.path == "/users"
    assert len(api.evidence) == 2 # One from fastapi, one from openapi

def test_malformed_openapi():
    fixture_path = os.path.join(FIXTURES_DIR, "malformed_openapi")
    result = analyze_services_and_dependencies(fixture_path)
    # Should not crash, just returns 0 APIs
    assert len(result.apis) == 0

def test_ambiguous_service():
    fixture_path = os.path.join(FIXTURES_DIR, "ambiguous_service")
    result = analyze_services_and_dependencies(fixture_path)
    
    assert len(result.apis) == 1
    # API is at root, but services are in subdirectories, so service_id should be null
    assert result.apis[0].service_id is None

def test_empty_project_api():
    fixture_path = os.path.join(FIXTURES_DIR, "empty_project_api")
    result = analyze_services_and_dependencies(fixture_path)
    assert len(result.apis) == 0
