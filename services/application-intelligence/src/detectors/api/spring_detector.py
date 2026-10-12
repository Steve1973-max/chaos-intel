import os
import re
from typing import List
from ...models.api import Api, ApiParameter
from ...models.technology import Evidence

def discover_spring_endpoints(filepath: str, rel_filepath: str) -> List[Api]:
    apis = []
    try:
        if os.path.getsize(filepath) > 2 * 1024 * 1024:
            return apis
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        controllers = re.finditer(r'@RequestMapping\s*\(\s*[\'"]([^\'"]*)[\'"]\s*\)', content)
        controller_prefixes = []
        for m in controllers:
            # We assume it's class level if it's before any method decorators, but regex makes it hard to be perfect.
            # We'll just track the latest @RequestMapping prefix before the route.
            controller_prefixes.append((m.start(), m.group(1)))
            
        route_matches = re.finditer(r'@(Get|Post|Put|Patch|Delete)Mapping(?:\s*\(\s*([\'"][^\'"]*[\'"])?\s*\))?', content)
        
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
                framework="Spring Boot",
                source=rel_filepath,
                parameters=params,
                confidence=0.9,
                evidence=[Evidence(
                    source=rel_filepath,
                    type="controller_decorator",
                    detail=f"@{method}Mapping('{path}')"
                )]
            ))
            
    except Exception:
        pass
        
    return apis
