import os
import re
from typing import List
from ...models.api import Api, ApiParameter
from ...models.technology import Evidence

def discover_flask_endpoints(filepath: str, rel_filepath: str) -> List[Api]:
    apis = []
    try:
        if os.path.getsize(filepath) > 2 * 1024 * 1024:
            return apis
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract route decorators: @app.route("/users", methods=["GET"])
        route_matches = re.finditer(r'@([a-zA-Z0-9_]+)\.route\s*\(\s*[\'"]([^\'"]+)[\'"](?:[^)]*methods\s*=\s*\[([^\]]+)\])?', content)
        for match in route_matches:
            router_name = match.group(1)
            path = match.group(2)
            methods_str = match.group(3)
            
            # Normalize path
            if path != '/' and path.endswith('/'):
                path = path.rstrip('/')
                
            methods = []
            if methods_str:
                methods = [m.strip().strip('\'"') for m in methods_str.split(',')]
            else:
                methods = ['GET'] # default for flask
                
            params = []
            # Flask uses <type:name> or <name> for path parameters
            path_params = re.findall(r'<(?:\w+:)?([a-zA-Z0-9_]+)>', path)
            for p in path_params:
                params.append(ApiParameter(name=p, location="path"))
                # Standardize to OpenAPI format {name}
                path = re.sub(rf'<(?:\w+:)?{p}>', f'{{{p}}}', path)
                
            for method in methods:
                method = method.upper()
                if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'):
                    continue
                    
                apis.append(Api(
                    api_id="",
                    method=method,
                    path=path,
                    framework="Flask",
                    source=rel_filepath,
                    parameters=params,
                    confidence=0.9,
                    evidence=[Evidence(
                        source=rel_filepath,
                        type="route_decorator",
                        detail=f"@{router_name}.route('{path}', methods={methods})"
                    )]
                ))
            
    except Exception:
        pass
        
    return apis
