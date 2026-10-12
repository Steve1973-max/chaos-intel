import os
import re
from typing import List, Dict, Set
from ..models.service import Service
from ..models.dependency import Dependency
from ..models.technology import Evidence
from .parsers.docker_compose import parse_docker_compose
from .parsers.config_parser import parse_env_file

IGNORED_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 
    'build', 'dist', 'cache', 'coverage'
}

def resolve_target_service_id(name_or_host: str, services: List[Service]) -> str:
    """Attempts to match a hostname or service name to a discovered service."""
    for svc in services:
        if svc.name == name_or_host:
            return svc.service_id
    return None

def deduplicate_dependencies(deps: List[Dependency]) -> List[Dependency]:
    """Deduplicate dependencies based on source_service_id, name, and type."""
    merged = {}
    for dep in deps:
        key = (dep.source_service_id, dep.name, dep.dependency_type)
        if key not in merged:
            merged[key] = dep
        else:
            # Merge evidence
            existing_ev = {f"{e.source}:{e.type}:{e.detail}" for e in merged[key].evidence}
            for ev in dep.evidence:
                ev_str = f"{ev.source}:{ev.type}:{ev.detail}"
                if ev_str not in existing_ev:
                    merged[key].evidence.append(ev)
                    existing_ev.add(ev_str)
            # Increase confidence slightly for multiple signals
            merged[key].confidence = min(0.99, merged[key].confidence + 0.1)
    return list(merged.values())

def discover_dependencies(source_path: str, services: List[Service]) -> List[Dependency]:
    dependencies = []
    
    if not os.path.isdir(source_path):
        return []

    # Map paths to services to know which service a file belongs to
    def get_service_for_path(filepath: str) -> Service:
        # Simplistic matching: if path starts with service source_path
        rel_path = os.path.relpath(filepath, source_path)
        matched_svc = None
        longest_match = -1
        for svc in services:
            if svc.source_path == ".":
                if matched_svc is None:
                    matched_svc = svc
            elif rel_path.startswith(svc.source_path) or rel_path.startswith(svc.source_path.replace('/', '\\')):
                if len(svc.source_path) > longest_match:
                    matched_svc = svc
                    longest_match = len(svc.source_path)
        return matched_svc

    for root, dirs, files in os.walk(source_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        
        for file in files:
            filepath = os.path.join(root, file)
            rel_filepath = os.path.relpath(filepath, source_path)
            
            # 1. Docker Compose Dependencies
            if file in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
                compose_data = parse_docker_compose(filepath)
                for svc_name, svc_data in compose_data.items():
                    source_svc_id = resolve_target_service_id(svc_name, services)
                    if not source_svc_id:
                        continue
                        
                    for target_name in svc_data.get('depends_on', []):
                        target_id = resolve_target_service_id(target_name, services)
                        dep_type = "unknown"
                        if target_id:
                            # Try to infer type from target service if possible
                            tgt_svc = next((s for s in services if s.service_id == target_id), None)
                            if tgt_svc:
                                if tgt_svc.type in ("database", "cache", "message_broker"):
                                    dep_type = tgt_svc.type
                                elif tgt_svc.type in ("frontend", "backend", "worker"):
                                    dep_type = "http"
                        
                        dependencies.append(Dependency(
                            source_service_id=source_svc_id,
                            target_service_id=target_id,
                            dependency_type=dep_type,
                            name=target_name,
                            confidence=0.9,
                            evidence=[Evidence(source=rel_filepath, type="docker_compose", detail=f"depends_on: {target_name}")]
                        ))
            
            # 2. Config File Dependencies (.env)
            if file.startswith('.env') or file.endswith('.properties'):
                svc = get_service_for_path(filepath)
                if svc:
                    env_deps = parse_env_file(filepath)
                    for key, target, dep_type in env_deps:
                        target_id = resolve_target_service_id(target, services)
                        dependencies.append(Dependency(
                            source_service_id=svc.service_id,
                            target_service_id=target_id,
                            dependency_type=dep_type,
                            name=target,
                            confidence=0.8,
                            evidence=[Evidence(source=rel_filepath, type="configuration", detail=f"{key}")]
                        ))
                        
            # 3. Simple Source File Dependencies (HTTP calls)
            if file.endswith(('.js', '.ts', '.py', '.java', '.go')):
                svc = get_service_for_path(filepath)
                if svc:
                    # Very simple static analysis for http://...
                    try:
                        if os.path.getsize(filepath) < 1024 * 1024:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                content = f.read()
                                urls = re.findall(r'https?://[a-zA-Z0-9_\-\.]+', content)
                                for url in urls:
                                    target = url.split("://")[1]
                                    target_id = resolve_target_service_id(target, services)
                                    dependencies.append(Dependency(
                                        source_service_id=svc.service_id,
                                        target_service_id=target_id,
                                        dependency_type="http" if not target_id else (next((s.type for s in services if s.service_id == target_id), "http")),
                                        name=target,
                                        confidence=0.5,
                                        evidence=[Evidence(source=rel_filepath, type="source_code", detail=f"found URL {url}")]
                                    ))
                    except Exception:
                        pass
                        
    return deduplicate_dependencies(dependencies)

