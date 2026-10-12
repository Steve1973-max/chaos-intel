import re
from typing import List, Dict
from .models import ApplicationReport

def escape_mermaid_label(label: str) -> str:
    """Escapes Mermaid sensitive characters in node labels."""
    if not label:
        return ""
    # Mermaid labels should not contain unescaped quotes or specific control chars
    # Enclose in quotes and escape internal quotes
    escaped = str(label).replace('"', '#quot;').replace('(', '#40;').replace(')', '#41;')
    return f'"{escaped}"'

def sanitize_id(raw_id: str) -> str:
    """Creates a safe Mermaid node identifier."""
    # Prefix with n_ to ensure it starts with a letter, and replace invalid chars
    safe = re.sub(r'[^a-zA-Z0-9]', '_', raw_id)
    return f"n_{safe}"

def generate_mermaid_report(report: ApplicationReport) -> str:
    """
    Generate a Mermaid architecture diagram from the application model.
    """
    lines: List[str] = ["graph TD"]
    
    graph = report.architecture
    
    if not graph.nodes:
        lines.append("    empty[\"Empty Architecture\"]")
        return "\n".join(lines)
    
    # Sort nodes and edges for deterministic output
    nodes = sorted(graph.nodes, key=lambda n: n.node_id)
    edges = sorted(graph.edges, key=lambda e: (e.source_node_id, e.target_node_id, e.edge_type))
    
    seen_nodes = set()
    
    for node in nodes:
        node_id = sanitize_id(node.node_id)
        if node_id not in seen_nodes:
            label = escape_mermaid_label(node.name)
            lines.append(f"    {node_id}[{label}]")
            seen_nodes.add(node_id)
            
    for edge in edges:
        source_id = sanitize_id(edge.source_node_id)
        target_id = sanitize_id(edge.target_node_id)
        
        # We assume the nodes might not have been declared if they were in edges but missing in nodes list
        if source_id not in seen_nodes:
            lines.append(f"    {source_id}[{escape_mermaid_label(edge.source_node_id)}]")
            seen_nodes.add(source_id)
        if target_id not in seen_nodes:
            lines.append(f"    {target_id}[{escape_mermaid_label(edge.target_node_id)}]")
            seen_nodes.add(target_id)
            
        edge_label = escape_mermaid_label(edge.edge_type) if edge.edge_type else "\"\""
        lines.append(f"    {source_id} -->|{edge_label}| {target_id}")
        
    return "\n".join(lines)
