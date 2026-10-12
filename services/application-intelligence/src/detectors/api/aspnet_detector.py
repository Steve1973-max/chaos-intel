import os
import re
from typing import List
from ...models.api import Api, ApiParameter
from ...models.technology import Evidence

def discover_aspnet_endpoints(filepath: str, rel_filepath: str) -> List[Api]:
    apis = []
    try:
        if os.path.getsize(filepath) > 2 * 1024 * 1024:
            return apis
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        controllers = re.finditer(r'\[Route\(\s*[\'"]([^\'"]*)[\'"]\s*\)\]', content)
        controller_prefixes = []
        for m in controllers:
            controller_prefixes.append((m.start(), m.group(1)))
            
        # Very simple class name detection for [controller] replacement
        class_match = re.search(r'class\s+([a-zA-Z0-9_]+)Controller', content)
        controller_name = class_match.group(1).lower() if class_match else "unknown"
            
        route_matches = re.finditer(r'\[Http(Get|Post|Put|Patch|Delete)\s*(?:\(\s*[\'"]([^\'"]*)[\'"]\s*\))?\]', content)
        
        for match in route_matches:
            method = match.group(1).upper()
            path_arg = match.group(2)
            path = ""
            if path_arg:
                path = path_arg.strip('\'"')
                
            prefix = ""
            for c_start, c_prefix in reversed(controller_prefixes):
                if c_start < match.start():
                    prefix = c_prefix
                    break
                    
            prefix = prefix.replace("[controller]", controller_name)
                    
            full_path = prefix
            if path:
                if not full_path.endswith('/') and not path.startswith('/'):
                    full_path += '/'
                full_path += path
                
            if not full_path.startswith('/'):
                full_path = '/' + full_path
                
            if full_path != '/' and full_path.endswith('/'):
                full_path = full_path.rstrip('/')
                
            params = []
            path_params = re.findall(r'\{([a-zA-Z0-9_]+)\}', full_path)
            for p in path_params:
                params.append(ApiParameter(name=p, location="path"))
                
            apis.append(Api(
                api_id="",
                method=method,
                path=full_path,
                framework="ASP.NET",
                source=rel_filepath,
                parameters=params,
                confidence=0.9,
                evidence=[Evidence(
                    source=rel_filepath,
                    type="route_decorator",
                    detail=f"[Http{method}('{path}')]"
                )]
            ))
            
    except Exception:
        pass
        
    return apis
