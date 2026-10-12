from typing import List, Set, Dict, Tuple
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class CyclicDependencyRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-cycle"

    @property
    def category(self) -> str:
        return "architecture"
        
    @property
    def risk_type(self) -> str:
        return "cyclic_dependency"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        
        # Build adjacency list
        adj: Dict[str, List[Tuple[str, str]]] = {n.node_id: [] for n in app.architecture.nodes}
        for edge in app.architecture.edges:
            if edge.source_node_id in adj:
                adj[edge.source_node_id].append((edge.target_node_id, edge.edge_id))
                
        visited = set()
        rec_stack = set()
        cycles = []
        path = []
        
        def dfs(node_id: str):
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)
            
            for neighbor, edge_id in adj.get(node_id, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Cycle detected
                    idx = path.index(neighbor)
                    cycle_nodes = path[idx:]
                    cycles.append((cycle_nodes, edge_id))
                    
            rec_stack.remove(node_id)
            path.pop()

        for node in app.architecture.nodes:
            if node.node_id not in visited:
                dfs(node.node_id)
                
        # Deduplicate cycles if necessary (simple approach here)
        reported = set()
        
        for cycle, edge_id in cycles:
            cycle_key = tuple(sorted(cycle))
            if cycle_key in reported:
                continue
            reported.add(cycle_key)
            
            names = [next(n.name for n in app.architecture.nodes if n.node_id == nid) for nid in cycle]
            cycle_str = " \u2192 ".join(names + [names[0]])
            
            finding = RiskFinding(
                risk_id=self.generate_risk_id(app.application_id, edge_id),
                application_id=app.application_id,
                category=self.category,
                risk_type=self.risk_type,
                severity=Severity.MEDIUM,
                title="Cyclic dependency",
                description=f"A cyclic dependency was detected: {cycle_str}",
                target_type="edge",
                target_id=edge_id,
                confidence=0.9,
                evidence=[Evidence(source="architecture", type="graph_cycle", detail=cycle_str)],
                indicators=[{"metric": "cycle_length", "value": len(cycle)}]
            )
            findings.append(finding)
                
        return findings
