import os
import yaml
import json
from typing import List, Dict, Any
from ...models.api import Api, ApiParameter
from ...models.technology import Evidence

def discover_openapi_endpoints(filepath: str, rel_filepath: str) -> List[Api]:
    apis = []
    try:
        # Avoid huge files
        if os.path.getsize(filepath) > 10 * 1024 * 1024:
            return apis
            
        with open(filepath, 'r', encoding='utf-8') as f:
            if filepath.endswith('.json'):
                data = json.load(f)
            else:
                data = yaml.safe_load(f)
                
        if not isinstance(data, dict):
            return apis
            
        # Is it OpenAPI?
        if 'openapi' not in data and 'swagger' not in data:
            return apis
            
        paths = data.get('paths', {})
        if not isinstance(paths, dict):
            return apis
            
        # Global security
        global_security = data.get('security', [])
        
        for path, path_obj in paths.items():
            if not isinstance(path_obj, dict):
                continue
                
            for method, operation in path_obj.items():
                if method.lower() not in ('get', 'post', 'put', 'patch', 'delete', 'options', 'head'):
                    continue
                    
                if not isinstance(operation, dict):
                    continue
                    
                params = []
                # Extract parameters (ignoring references for simplicity for now, or just capturing raw)
                for p in operation.get('parameters', []):
                    if isinstance(p, dict) and 'name' in p and 'in' in p:
                        params.append(ApiParameter(
                            name=p['name'],
                            location=p['in'] if p['in'] in ('path', 'query', 'header', 'cookie') else 'unknown'
                        ))
                        
                req_body = operation.get('requestBody')
                res_info = operation.get('responses')
                
                auth_req = None
                sec = operation.get('security')
                if sec is not None:
                    auth_req = len(sec) > 0
                elif global_security:
                    auth_req = len(global_security) > 0
                    
                # Create a placeholder API object, IDs will be normalized by the registry
                api = Api(
                    api_id="", # filled by registry
                    method=method.upper(),
                    path=path,
                    framework="openapi",
                    source=rel_filepath,
                    parameters=params,
                    request_body=req_body,
                    response_information=res_info,
                    auth_required=auth_req,
                    confidence=0.99,
                    evidence=[Evidence(
                        source=rel_filepath,
                        type="openapi",
                        detail=f"{method.upper()} {path}"
                    )]
                )
                apis.append(api)
    except Exception:
        pass
        
    return apis
