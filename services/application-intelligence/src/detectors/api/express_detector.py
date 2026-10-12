import os
import re
from typing import List
from ...models.api import Api, ApiParameter
from ...models.technology import Evidence

def discover_express_endpoints(filepath: str, rel_filepath: str) -> List[Api]:
    apis = []
    try:
        if os.path.getsize(filepath) > 2 * 1024 * 1024:
            return apis
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract app.use prefixes: app.use("/api", router)
        router_prefixes = {}
        use_matches = re.finditer(r'(?:app|router)\.use\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*([a-zA-Z0-9_]+)', content)
        for match in use_matches:
            prefix = match.group(1)
            router_name = match.group(2)
            router_prefixes[router_name] = prefix
            
        # Extract route definitions: app.get("/users")
        route_matches = re.finditer(r'([a-zA-Z0-9_]+)\.(get|post|put|patch|delete|options|head)\s*\(\s*[\'"]([^\'"]+)[\'"]', content)
        for match in route_matches:
            router_name = match.group(1)
            method = match.group(2).upper()
            path = match.group(3)
            
            # Combine prefix if it's a known router
            if router_name in router_prefixes:
                prefix = router_prefixes[router_name]
                path = prefix + path
                
            # Normalize path
            if path != '/' and path.endswith('/'):
                path = path.rstrip('/')
                
            # Extract parameters: :id
            params = []
            path_params = re.findall(r':([a-zA-Z0-9_]+)', path)
            for p in path_params:
                params.append(ApiParameter(name=p, location="path"))
                # Normalize to {id} instead of :id for consistency (optional but helpful)
                # But user asked: "Preserve meaningful path parameters: /users/:id. Do NOT aggressively rewrite if doing so loses information."
                # I'll leave as :id but extract the parameter.
                
            apis.append(Api(
                api_id="",
                method=method,
                path=path,
                framework="Express",
                source=rel_filepath,
                parameters=params,
                confidence=0.9,
                evidence=[Evidence(
                    source=rel_filepath,
                    type="route_definition",
                    detail=f"{router_name}.{method.lower()}('{path}')"
                )]
            ))
            
    except Exception:
        pass
        
    return apis
