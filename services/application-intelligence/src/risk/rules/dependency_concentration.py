from typing import List
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class DependencyConcentrationRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-dep-conc"

    @property
    def category(self) -> str:
        return "architecture"
        
    @property
    def risk_type(self) -> str:
        return "dependency_concentration"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        
        incoming = {}
        for edge in app.architecture.edges:
            incoming[edge.target_node_id] = incoming.get(edge.target_node_id, 0) + 1
            
        for node in app.architecture.nodes:
            # If a service acts as a hub
            if node.node_type not in ("frontend", "backend", "worker", "service", "gateway"):
                continue
                
            inc_count = incoming.get(node.node_id, 0)
            if inc_count >= 3:
                finding = RiskFinding(
                    risk_id=self.generate_risk_id(app.application_id, node.node_id),
                    application_id=app.application_id,
                    category=self.category,
                    risk_type=self.risk_type,
                    severity=Severity.MEDIUM,
                    title="Dependency concentration",
                    description=f"{node.name} is a central hub receiving {inc_count} incoming dependencies.",
                    target_type="node",
                    target_id=node.node_id,
                    confidence=0.85,
                    evidence=[Evidence(source="architecture", type="graph_analysis", detail=f"{node.name} receives {inc_count} dependencies")],
                    indicators=[{"metric": "incoming_dependency_count", "value": inc_count}]
                )
                findings.append(finding)
                
        return findings
