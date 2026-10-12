from typing import List
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class CriticalDependencyRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-crit-dep"

    @property
    def category(self) -> str:
        return "dependency"
        
    @property
    def risk_type(self) -> str:
        return "critical_dependency"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        
        incoming = {}
        for edge in app.architecture.edges:
            incoming[edge.target_node_id] = incoming.get(edge.target_node_id, 0) + 1
            
        for edge in app.architecture.edges:
            source_node = next((n for n in app.architecture.nodes if n.node_id == edge.source_node_id), None)
            target_node = next((n for n in app.architecture.nodes if n.node_id == edge.target_node_id), None)
            
            if not source_node or not target_node:
                continue
                
            # If backend depends on a database, and the backend is centrally relied upon, or database is shared
            if target_node.node_type in ("database", "postgres", "mysql", "mongodb"):
                source_incoming = incoming.get(source_node.node_id, 0)
                target_incoming = incoming.get(target_node.node_id, 0)
                
                if source_incoming > 0 or target_incoming > 1:
                    finding = RiskFinding(
                        risk_id=self.generate_risk_id(app.application_id, edge.edge_id),
                        application_id=app.application_id,
                        category=self.category,
                        risk_type=self.risk_type,
                        severity=Severity.HIGH if target_incoming > 1 else Severity.MEDIUM,
                        title="Critical dependency",
                        description=f"{source_node.name} relies heavily on {target_node.name} which is structurally central.",
                        target_type="edge",
                        target_id=edge.edge_id,
                        confidence=0.8,
                        evidence=[Evidence(source="architecture", type="graph_relationship", detail=f"{source_node.name} \u2192 {target_node.name}")],
                        indicators=[{"metric": "target_incoming", "value": target_incoming}]
                    )
                    findings.append(finding)
                
        return findings
