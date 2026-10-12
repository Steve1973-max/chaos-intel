import os
import yaml
from typing import Dict, Any, List

def parse_docker_compose(filepath: str) -> Dict[str, Any]:
    """
    Safely parses a docker-compose.yml file.
    Extracts services, builds, depends_on, ports, and environment variables.
    """
    result = {}
    if not os.path.exists(filepath):
        return result
        
    # Prevent reading huge files
    if os.path.getsize(filepath) > 5 * 1024 * 1024:
        return result

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            
        if not data or not isinstance(data, dict):
            return result
            
        services = data.get('services', {})
        if not isinstance(services, dict):
            return result
            
        for svc_name, svc_def in services.items():
            if not isinstance(svc_def, dict):
                continue
                
            parsed_svc = {
                'name': svc_name,
                'build_context': None,
                'image': svc_def.get('image'),
                'depends_on': [],
                'ports': [],
                'environment': []
            }
            
            # Extract build context
            build = svc_def.get('build')
            if isinstance(build, str):
                parsed_svc['build_context'] = build
            elif isinstance(build, dict):
                parsed_svc['build_context'] = build.get('context')
                
            # Extract depends_on
            depends_on = svc_def.get('depends_on')
            if isinstance(depends_on, list):
                parsed_svc['depends_on'] = depends_on
            elif isinstance(depends_on, dict):
                parsed_svc['depends_on'] = list(depends_on.keys())
                
            # Extract ports
            ports = svc_def.get('ports')
            if isinstance(ports, list):
                for p in ports:
                    if isinstance(p, (str, int)):
                        # Simple extraction of host port mapping
                        port_str = str(p)
                        if ':' in port_str:
                            try:
                                # target port is usually the last part: "8080:80" -> 80
                                target = port_str.split(':')[-1]
                                # remove protocol like /tcp
                                target = target.split('/')[0]
                                parsed_svc['ports'].append(int(target))
                            except ValueError:
                                pass
                        else:
                            try:
                                parsed_svc['ports'].append(int(port_str.split('/')[0]))
                            except ValueError:
                                pass

            # Extract environment (only keys for safety)
            env = svc_def.get('environment')
            if isinstance(env, dict):
                parsed_svc['environment'] = list(env.keys())
            elif isinstance(env, list):
                for e in env:
                    if '=' in str(e):
                        parsed_svc['environment'].append(str(e).split('=')[0])
            
            result[svc_name] = parsed_svc
            
    except Exception:
        pass
        
    return result
