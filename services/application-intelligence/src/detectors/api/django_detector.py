import os
import re
from typing import List
from ...models.api import Api, ApiParameter
from ...models.technology import Evidence

def discover_django_endpoints(filepath: str, rel_filepath: str) -> List[Api]:
    apis = []
    try:
        if os.path.getsize(filepath) > 2 * 1024 * 1024:
            return apis
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract path definitions (handles path('...') and re_path(r'...'))
        path_matches = re.finditer(r'(?:path|re_path)\s*\(\s*r?[\'"]([^\'"]+)[\'"]', content)
        for match in path_matches:
            path = match.group(1)
            
            method = "GET"
            
            # Normalize path
            if not path.startswith('/'):
                path = '/' + path
            if path != '/' and path.endswith('/'):
                path = path.rstrip('/')
                
            # Extract parameters: <int:id> or <id> or (?P<year>...)
            params = []
            
            # Handle Django re_path named groups (?P<name>pattern) first
            re_params = re.findall(r'\(\?P<([a-zA-Z0-9_]+)>[^)]+\)', path)
            for p in re_params:
                if not any(x.name == p for x in params):
                    params.append(ApiParameter(name=p, location="path"))
                # Simplified normalization for regex routes
                path = re.sub(rf'\(\?P<{p}>[^)]+\)', f'{{{p}}}', path)
            
            # Handle Django 2.x+ path parameters (ignore any remaining regex artifacts)
            path_params = re.findall(r'<(?:\w+:)?([a-zA-Z0-9_]+)>', path)
            for p in path_params:
                if not any(x.name == p for x in params):
                    params.append(ApiParameter(name=p, location="path"))
                path = re.sub(rf'<(?:\w+:)?{p}>', f'{{{p}}}', path)
                
            # Clean up typical regex anchors in path if they exist
            path = path.replace('^', '').replace('$', '')
            
            # Ensure it's normalized one last time
            if path != '/' and path.endswith('/'):
                path = path.rstrip('/')
                
            apis.append(Api(
                api_id="",
                method=method,
                path=path,
                framework="Django",
                source=rel_filepath,
                parameters=params,
                confidence=0.7, # Lower confidence since we don't know methods exactly
                evidence=[Evidence(
                    source=rel_filepath,
                    type="route_definition",
                    detail=f"path('{path}')"
                )]
            ))
            
    except Exception:
        pass
        
    return apis
