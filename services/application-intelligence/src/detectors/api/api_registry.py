import hashlib
from typing import List, Dict
from ...models.api import Api
from ...models.service import Service

def generate_api_id(app_id: str, service_id: str, method: str, normalized_path: str) -> str:
    """Generate a deterministic ID for an API endpoint."""
    hash_obj = hashlib.md5(f"{app_id}:{service_id}:{method}:{normalized_path}".encode('utf-8'))
    return f"api-{hash_obj.hexdigest()[:8]}"

def merge_apis(apis: List[Api]) -> List[Api]:
    """Deduplicates APIs by merging evidence when IDs match."""
    merged: Dict[str, Api] = {}
    
    for api in apis:
        if api.api_id not in merged:
            merged[api.api_id] = api
        else:
            existing = merged[api.api_id]
            # Merge evidence
            existing_ev = {f"{e.source}:{e.type}:{e.detail}" for e in existing.evidence}
            for ev in api.evidence:
                ev_str = f"{ev.source}:{ev.type}:{ev.detail}"
                if ev_str not in existing_ev:
                    existing.evidence.append(ev)
                    existing_ev.add(ev_str)
                    
            # Increase confidence
            existing.confidence = min(0.99, existing.confidence + 0.05)
            
            # Prefer OpenAPI framework label over specific frameworks if merging
            if api.framework == "openapi" or existing.framework == "openapi":
                existing.framework = "openapi"
                
            # Merge parameters
            existing_params = {p.name for p in existing.parameters}
            for p in api.parameters:
                if p.name not in existing_params:
                    existing.parameters.append(p)
                    existing_params.add(p.name)
                    
            # Merge security
            if existing.auth_required is None and api.auth_required is not None:
                existing.auth_required = api.auth_required
                
    return list(merged.values())

def associate_api_to_service(rel_filepath: str, services: List[Service]) -> str:
    """Find the best matching service for a file path."""
    best_svc = None
    longest_match = -1
    
    for svc in services:
        if svc.source_path == ".":
            if best_svc is None:
                best_svc = svc
        else:
            if rel_filepath.startswith(svc.source_path) or rel_filepath.startswith(svc.source_path.replace('/', '\\')):
                if len(svc.source_path) > longest_match:
                    best_svc = svc
                    longest_match = len(svc.source_path)
                    
    return best_svc.service_id if best_svc else None
