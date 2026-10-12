import os
from typing import List
from ..models.api import Api
from ..models.service import Service
from .api.openapi_detector import discover_openapi_endpoints
from .api.fastapi_detector import discover_fastapi_endpoints
from .api.flask_detector import discover_flask_endpoints
from .api.django_detector import discover_django_endpoints
from .api.express_detector import discover_express_endpoints
from .api.nestjs_detector import discover_nestjs_endpoints
from .api.spring_detector import discover_spring_endpoints
from .api.aspnet_detector import discover_aspnet_endpoints
from .api.api_registry import associate_api_to_service, generate_api_id, merge_apis

IGNORED_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 
    'build', 'dist', 'cache', 'coverage'
}

def discover_apis(source_path: str, services: List[Service], app_id: str = "app-default") -> List[Api]:
    apis = []
    
    if not os.path.isdir(source_path):
        return []

    for root, dirs, files in os.walk(source_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        
        for file in files:
            filepath = os.path.join(root, file)
            rel_filepath = os.path.relpath(filepath, source_path)
            
            # OpenAPI Detection
            if file in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.yml", "swagger.json"):
                apis.extend(discover_openapi_endpoints(filepath, rel_filepath))
                
            # FastAPI, Flask, Django Detection
            if file.endswith('.py'):
                apis.extend(discover_fastapi_endpoints(filepath, rel_filepath))
                apis.extend(discover_flask_endpoints(filepath, rel_filepath))
                apis.extend(discover_django_endpoints(filepath, rel_filepath))
                
            # Express, NestJS Detection
            if file.endswith('.js') or file.endswith('.ts'):
                apis.extend(discover_express_endpoints(filepath, rel_filepath))
                apis.extend(discover_nestjs_endpoints(filepath, rel_filepath))
                
            # Spring Boot Detection
            if file.endswith('.java'):
                apis.extend(discover_spring_endpoints(filepath, rel_filepath))
                
            # ASP.NET Detection
            if file.endswith('.cs'):
                apis.extend(discover_aspnet_endpoints(filepath, rel_filepath))
                
    # Finalize APIs (associate with service, generate ID)
    for api in apis:
        svc_id = associate_api_to_service(api.source, services)
        api.service_id = svc_id
        
        # If we can't find a service, it stays null but we still assign a deterministic ID using "null"
        safe_svc_id = svc_id if svc_id else "null_svc"
        api.api_id = generate_api_id(app_id, safe_svc_id, api.method, api.path)
        
    # Deduplicate
    return merge_apis(apis)
