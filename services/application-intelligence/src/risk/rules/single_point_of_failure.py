from typing import List
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class SinglePointOfFailureRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-spof"

    @property
    def category(self) -> str:
        return "architecture"
        
    @property
    def risk_type(self) -> str:
        return "single_point_of_failure"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        
        incoming = {}
        for edge in app.architecture.edges:
            incoming[edge.target_node_id] = incoming.get(edge.target_node_id, 0) + 1
            
        is_monolith = len(app.services) == 1
        
        for node in app.architecture.nodes:
            if node.node_type not in ("frontend", "backend", "service", "worker"):
                continue
                
            inc_count = incoming.get(node.node_id, 0)
            
            # If it receives traffic, it's a potential SPOF
            if inc_count > 0 or is_monolith:
                if is_monolith:
                    severity = Severity.LOW
                elif inc_count > 2:
                    severity = Severity.HIGH
                else:
                    severity = Severity.MEDIUM
                    
                finding = RiskFinding(
                    risk_id=self.generate_risk_id(app.application_id, node.node_id),
                    application_id=app.application_id,
                    category=self.category,
                    risk_type=self.risk_type,
                    severity=severity,
                    title="Potential single point of failure",
                    description=f"The {node.name} service handles incoming dependencies but has no explicit redundancy detected.",
                    target_type="node",
                    target_id=node.node_id,
                    confidence=0.7,
                    evidence=[Evidence(source="architecture", type="graph_relationship", detail=f"{node.name} has {inc_count} incoming dependencies")],
                    indicators=[{"metric": "incoming_dependency_count", "value": inc_count}]
                )
                findings.append(finding)
                
        return findings
