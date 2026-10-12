import os
import re
from typing import List
from ...models.api import Api, ApiParameter
from ...models.technology import Evidence

def discover_fastapi_endpoints(filepath: str, rel_filepath: str) -> List[Api]:
    apis = []
    try:
        if os.path.getsize(filepath) > 2 * 1024 * 1024:
            return apis
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract APIRouter prefixes: router = APIRouter(prefix="/api")
        router_prefixes = {}
        router_matches = re.finditer(r'([a-zA-Z0-9_]+)\s*=\s*APIRouter\s*\([^)]*prefix\s*=\s*[\'"]([^\'"]+)[\'"]', content)
        for match in router_matches:
            router_name = match.group(1)
            prefix = match.group(2)
            router_prefixes[router_name] = prefix
            
        # Extract route decorators: @app.get("/users") or @router.post("/items")
        route_matches = re.finditer(r'@([a-zA-Z0-9_]+)\.(get|post|put|patch|delete|options|head)\s*\(\s*[\'"]([^\'"]+)[\'"]', content)
        for match in route_matches:
            router_name = match.group(1)
            method = match.group(2).upper()
            path = match.group(3)
            
            # Combine prefix if it's a known router
            if router_name in router_prefixes:
                prefix = router_prefixes[router_name]
                path = prefix + path
                
            # Normalize path (e.g. remove trailing slash unless it's just '/')
            if path != '/' and path.endswith('/'):
                path = path.rstrip('/')
                
            # Extract path parameters: {id}
            params = []
            path_params = re.findall(r'\{([a-zA-Z0-9_]+)\}', path)
            for p in path_params:
                params.append(ApiParameter(name=p, location="path"))
                
            apis.append(Api(
                api_id="",
                method=method,
                path=path,
                framework="FastAPI",
                source=rel_filepath,
                parameters=params,
                confidence=0.9,
                evidence=[Evidence(
                    source=rel_filepath,
                    type="route_decorator",
                    detail=f"@{router_name}.{method.lower()}('{path}')"
                )]
            ))
            
    except Exception:
        pass
        
    return apis
