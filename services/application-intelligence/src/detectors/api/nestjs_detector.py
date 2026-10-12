import os
import re
from typing import List
from ...models.api import Api, ApiParameter
from ...models.technology import Evidence

def discover_nestjs_endpoints(filepath: str, rel_filepath: str) -> List[Api]:
    apis = []
    try:
        if os.path.getsize(filepath) > 2 * 1024 * 1024:
            return apis
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # First, find class Controllers
        # Because we're doing naive regex, we split by class to get the controller prefix.
        classes = re.split(r'class\s+[a-zA-Z0-9_]+\s*\{', content)
        if len(classes) < 2:
            # no classes found, maybe try naive global search
            classes = [content]
        else:
            # Reattach the preceding decorators to the class body
            # Wait, splitting by class removes the decorators which are before `class`.
            pass
            
        # Better approach: find @Controller('prefix') and then find all @Get('path') until next @Controller
        controllers = re.finditer(r'@Controller\s*\(\s*[\'"]([^\'"]*)[\'"]\s*\)', content)
        controller_prefixes = []
        for m in controllers:
            controller_prefixes.append((m.start(), m.group(1)))
            
        route_matches = re.finditer(r'@(Get|Post|Put|Patch|Delete|Options|Head)\s*\(\s*([\'"][^\'"]*[\'"])?\s*\)', content)
        
        for match in route_matches:
            method = match.group(1).upper()
            path_arg = match.group(2)
            path = ""
            if path_arg:
                path = path_arg.strip('\'"')
                
            # Find the closest preceding controller
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
            path_params = re.findall(r':([a-zA-Z0-9_]+)', full_path)
            for p in path_params:
                params.append(ApiParameter(name=p, location="path"))
                
            apis.append(Api(
                api_id="",
                method=method,
                path=full_path,
                framework="NestJS",
                source=rel_filepath,
                parameters=params,
                confidence=0.9,
                evidence=[Evidence(
                    source=rel_filepath,
                    type="controller_decorator",
                    detail=f"@{method}('{path}') in @Controller('{prefix}')"
                )]
            ))
            
    except Exception:
        pass
        
    return apis
