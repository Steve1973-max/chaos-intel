import os
import hashlib
from typing import List, Dict, Set
from ..models.service import Service
from ..models.technology import Evidence
from .parsers.docker_compose import parse_docker_compose
from .parsers.kubernetes import parse_kubernetes_manifest
from .technology_registry import REGISTRY

IGNORED_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 
    'build', 'dist', 'cache', 'coverage', 'models', 'controllers', 
    'utils', 'repositories', 'components', 'services', 'hooks'
}

def generate_service_id(app_id: str, identifier: str) -> str:
    """Generate a stable deterministic ID for a service."""
    hash_obj = hashlib.md5(f"{app_id}:{identifier}".encode('utf-8'))
    return f"svc-{hash_obj.hexdigest()[:8]}"

def guess_service_type(name: str, path: str, tech_hints: Set[str]) -> str:
    name_lower = name.lower()
    path_lower = path.lower()
    
    if "frontend" in name_lower or "web" in name_lower or "ui" in name_lower or "react" in tech_hints or "vue" in tech_hints or "next.js" in tech_hints:
        return "frontend"
    if "backend" in name_lower or "api" in name_lower or "fastapi" in tech_hints or "express" in tech_hints or "django" in tech_hints:
        return "backend"
    if "worker" in name_lower or "celery" in name_lower or "queue" in name_lower:
        return "worker"
    if "db" in name_lower or "postgres" in name_lower or "mysql" in name_lower or "mongo" in name_lower:
        return "database"
    if "redis" in name_lower or "cache" in name_lower:
        return "cache"
    if "rabbit" in name_lower or "kafka" in name_lower or "broker" in name_lower:
        return "message_broker"
    return "unknown"

def discover_services(source_path: str, app_id: str = "app-default") -> List[Service]:
    services_map: Dict[str, Service] = {}
    
    if not os.path.isdir(source_path):
        return []

    # 1. Discover via docker-compose
    for root, dirs, files in os.walk(source_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        
        for file in files:
            if file in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
                filepath = os.path.join(root, file)
                rel_filepath = os.path.relpath(filepath, source_path)
                compose_data = parse_docker_compose(filepath)
                
                for svc_name, svc_data in compose_data.items():
                    svc_path = svc_data.get('build_context')
                    if svc_path and isinstance(svc_path, str):
                        # Normalize path
                        svc_path = os.path.normpath(os.path.join(root, svc_path))
                        rel_path = os.path.relpath(svc_path, source_path)
                        # Fix up path if it points outside the root, keep it logical
                        if rel_path.startswith(".."):
                            rel_path = svc_name
                    else:
                        rel_path = svc_name # logical service
                    
                    svc_id = generate_service_id(app_id, svc_name)
                    svctype = guess_service_type(svc_name, rel_path, set())
                    
                    if svc_id not in services_map:
                        services_map[svc_id] = Service(
                            service_id=svc_id,
                            application_id=app_id,
                            name=svc_name,
                            type=svctype,
                            source_path=rel_path,
                            ports=svc_data.get('ports', []),
                            confidence=0.9,
                            evidence=[Evidence(source=rel_filepath, type="docker_compose", detail=f"service: {svc_name}")]
                        )

    # 2. Discover via top-level manifests if no compose found
    if not services_map:
        for item in os.listdir(source_path):
            item_path = os.path.join(source_path, item)
            if os.path.isdir(item_path) and item not in IGNORED_DIRS:
                # Check if this dir has a package.json or requirements.txt
                has_manifest = False
                for manifest in ("package.json", "requirements.txt", "pom.xml", "go.mod"):
                    if os.path.exists(os.path.join(item_path, manifest)):
                        has_manifest = True
                        break
                
                if has_manifest:
                    svc_id = generate_service_id(app_id, item)
                    svctype = guess_service_type(item, item, set())
                    services_map[svc_id] = Service(
                        service_id=svc_id,
                        application_id=app_id,
                        name=item,
                        type=svctype,
                        source_path=item,
                        confidence=0.7,
                        evidence=[Evidence(source=item, type="directory_manifest", detail="contains application manifest")]
                    )
    
    # 3. Discover Kubernetes Manifests
    for root, dirs, files in os.walk(source_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for file in files:
            if file.endswith(('.yaml', '.yml')) and 'compose' not in file:
                filepath = os.path.join(root, file)
                k8s_resources = parse_kubernetes_manifest(filepath)
                rel_filepath = os.path.relpath(filepath, source_path)
                for res in k8s_resources:
                    svc_name = res['name']
                    svc_id = generate_service_id(app_id, svc_name)
                    if svc_id not in services_map:
                        svctype = guess_service_type(svc_name, svc_name, set())
                        services_map[svc_id] = Service(
                            service_id=svc_id,
                            application_id=app_id,
                            name=svc_name,
                            type=svctype,
                            source_path="kubernetes",
                            confidence=0.8,
                            evidence=[Evidence(source=rel_filepath, type="kubernetes", detail=f"{res['kind']}: {svc_name}")]
                        )

    # 4. Fallback if still empty (assume single monolithic service)
    if not services_map:
        # Check if project has actual files
        has_files = False
        for root, dirs, files in os.walk(source_path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            if files:
                has_files = True
                break
                
        if has_files:
            svc_id = generate_service_id(app_id, "monolith")
            services_map[svc_id] = Service(
                service_id=svc_id,
                application_id=app_id,
                name="monolith",
                type="unknown",
                source_path=".",
                confidence=0.5,
                evidence=[Evidence(source=".", type="fallback", detail="monolithic fallback")]
            )

    return list(services_map.values())
