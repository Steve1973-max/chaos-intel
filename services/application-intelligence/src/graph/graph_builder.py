import hashlib
from typing import List, Dict, Any
from urllib.parse import urlparse

from ..models.architecture import ArchitectureGraph, GraphNode, GraphEdge
from ..models.service import Service
from ..models.dependency import Dependency
from ..models.api import Api
from ..models.technology import Technology, Evidence

def generate_node_id(node_type: str, name: str) -> str:
    hash_obj = hashlib.md5(f"{node_type}:{name}".encode('utf-8'))
    return f"node-{hash_obj.hexdigest()[:8]}"

def generate_edge_id(source_id: str, target_id: str, edge_type: str) -> str:
    hash_obj = hashlib.md5(f"{source_id}:{target_id}:{edge_type}".encode('utf-8'))
    return f"edge-{hash_obj.hexdigest()[:8]}"

def normalize_url(url: str) -> str:
    # Safely strip credentials from URLs
    try:
        if not url.startswith(('http://', 'https://')):
            # Sometimes targets are just "api.stripe.com"
            return url
        parsed = urlparse(url)
        return parsed.hostname or url
    except Exception:
        return url

def get_service_technologies(service_path: str, technologies: List[Technology]) -> List[str]:
    # Finds technologies where the evidence points to this service
    # If the service path is '.', it's root, so we check if evidence matches root
    # But for simplicity, we can just grab technologies that have evidence starting with service_path
    techs = set()
    for t in technologies:
        for ev in t.evidence:
            if hasattr(ev, 'source') and ev.source:
                # Normalize paths for comparison
                ev_source = ev.source.replace('\\', '/')
                svc_path = service_path.replace('\\', '/')
                if svc_path == "." or ev_source.startswith(svc_path):
                    techs.add(t.name)
    return sorted(list(techs))

def build_architecture_graph(
    services: List[Service], 
    dependencies: List[Dependency], 
    apis: List[Api], 
    technologies: List[Technology]
) -> ArchitectureGraph:
    nodes: Dict[str, GraphNode] = {}
    edges: Dict[str, GraphEdge] = {}
    
    # 1. Create nodes for all services
    for svc in services:
        node_type = svc.type or "unknown"
        node_id = generate_node_id(node_type, svc.name)
        
        tech_refs = get_service_technologies(svc.source_path, technologies)
        
        nodes[node_id] = GraphNode(
            node_id=node_id,
            node_type=node_type,
            name=svc.name,
            service_id=svc.service_id,
            technology_references=tech_refs,
            confidence=0.9,
            evidence=[Evidence(source=svc.source_path, type="service", detail=f"Discovered service: {svc.name}")]
        )

    infra_types = {"database", "cache", "message_queue", "message_broker", "postgres", "redis", "mysql", "mongodb", "kafka", "rabbitmq"}
    
    # 2. Process dependencies to build edges and external/infra nodes
    for dep in dependencies:
        source_svc = next((s for s in services if s.service_id == dep.source_service_id), None)
        if not source_svc:
            continue
            
        source_node_type = source_svc.type or "unknown"
        source_node_id = generate_node_id(source_node_type, source_svc.name)
        
        target_node_id = None
        target_node_type = "unknown"
        target_name = dep.name
        
        if dep.target_service_id:
            # Internal service
            target_svc = next((s for s in services if s.service_id == dep.target_service_id), None)
            if target_svc:
                target_node_type = target_svc.type or "unknown"
                target_name = target_svc.name
                target_node_id = generate_node_id(target_node_type, target_name)
        else:
            # External or Infra
            if dep.dependency_type in infra_types:
                target_node_type = dep.dependency_type
            elif dep.dependency_type in ("external_api", "http") or target_name.startswith(('http://', 'https://')):
                target_node_type = "external_service"
                target_name = normalize_url(target_name)
            else:
                target_node_type = "unknown"
                
            target_node_id = generate_node_id(target_node_type, target_name)
            
            # Create external/infra node if not exists
            if target_node_id not in nodes:
                nodes[target_node_id] = GraphNode(
                    node_id=target_node_id,
                    node_type=target_node_type,
                    name=target_name,
                    confidence=0.8,
                    evidence=dep.evidence
                )
        
        if target_node_id and target_node_id in nodes:
            edge_type = dep.dependency_type
            protocol = "http" if edge_type in ("http", "external_api") else None
            edge_id = generate_edge_id(source_node_id, target_node_id, edge_type)
            
            if edge_id not in edges:
                edges[edge_id] = GraphEdge(
                    edge_id=edge_id,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    edge_type=edge_type,
                    protocol=protocol,
                    confidence=dep.confidence,
                    evidence=list(dep.evidence)
                )
            else:
                # Deduplicate and merge edge evidence
                existing_ev = {f"{e.source}:{e.type}:{e.detail}" for e in edges[edge_id].evidence}
                for ev in dep.evidence:
                    ev_str = f"{ev.source}:{ev.type}:{ev.detail}"
                    if ev_str not in existing_ev:
                        edges[edge_id].evidence.append(ev)
                        existing_ev.add(ev_str)

    # Convert to sorted lists for determinism
    sorted_nodes = sorted(list(nodes.values()), key=lambda n: n.node_id)
    sorted_edges = sorted(list(edges.values()), key=lambda e: e.edge_id)
    
    return ArchitectureGraph(nodes=sorted_nodes, edges=sorted_edges)
