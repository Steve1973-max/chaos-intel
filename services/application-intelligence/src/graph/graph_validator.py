from typing import List
from ..models.architecture import ArchitectureGraph

def validate_graph(graph: ArchitectureGraph) -> List[str]:
    errors = []
    
    node_ids = set()
    for n in graph.nodes:
        if n.node_id in node_ids:
            errors.append(f"Duplicate node ID found: {n.node_id}")
        node_ids.add(n.node_id)
        
    edge_ids = set()
    for e in graph.edges:
        if e.edge_id in edge_ids:
            errors.append(f"Duplicate edge ID found: {e.edge_id}")
        edge_ids.add(e.edge_id)
        
    for edge in graph.edges:
        if edge.source_node_id not in node_ids:
            errors.append(f"Edge {edge.edge_id} has invalid source {edge.source_node_id}")
        if edge.target_node_id not in node_ids:
            errors.append(f"Edge {edge.edge_id} has invalid target {edge.target_node_id}")
            
    return errors
