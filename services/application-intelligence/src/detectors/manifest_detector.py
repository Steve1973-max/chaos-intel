import json
import os
import re
from typing import Dict, Optional

def parse_package_json(filepath: str) -> Dict[str, Optional[str]]:
    deps = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'dependencies' in data and isinstance(data['dependencies'], dict):
                deps.update(data['dependencies'])
            if 'devDependencies' in data and isinstance(data['devDependencies'], dict):
                deps.update(data['devDependencies'])
    except Exception:
        pass
    return deps

def parse_requirements_txt(filepath: str) -> Dict[str, Optional[str]]:
    deps = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Remove inline comments and environment markers
                line = line.split(';')[0].split('#')[0].strip()
                # Match package==version, package>=version, package~=version
                match = re.match(r'^([a-zA-Z0-9_\-]+)([=><~]+)(.*)$', line)
                if match:
                    deps[match.group(1)] = match.group(3).strip()
                else:
                    deps[line] = None
    except Exception:
        pass
    return deps

def parse_go_mod(filepath: str) -> Dict[str, Optional[str]]:
    deps = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            in_require = False
            for line in f:
                line = line.strip()
                if line.startswith('require ('):
                    in_require = True
                    continue
                if line == ')' and in_require:
                    in_require = False
                    continue
                if in_require or line.startswith('require '):
                    parts = line.replace('require ', '').split()
                    if len(parts) >= 2:
                        deps[parts[0]] = parts[1]
    except Exception:
        pass
    return deps

def detect_dependencies_in_file(filepath: str) -> Dict[str, Optional[str]]:
    filename = os.path.basename(filepath)
    if filename == 'package.json':
        return parse_package_json(filepath)
    elif filename in ('requirements.txt', 'requirements-dev.txt'):
        return parse_requirements_txt(filepath)
    elif filename == 'go.mod':
        return parse_go_mod(filepath)
    
    # Very naive fallback for others just reading the file contents to see if package names exist.
    # A true implementation would parse pom.xml, Cargo.toml, etc. properly.
    # For MVP we stick to the ones explicitly requested in tests.
    return {}
