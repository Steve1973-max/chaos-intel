from typing import List
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class ExternalDependencyRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-ext-dep"

    @property
    def category(self) -> str:
        return "dependency"
        
    @property
    def risk_type(self) -> str:
        return "external_dependency"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        
        for node in app.architecture.nodes:
            if node.node_type == "external_service":
                # Find who depends on it
                for edge in app.architecture.edges:
                    if edge.target_node_id == node.node_id:
                        source_node = next((n for n in app.architecture.nodes if n.node_id == edge.source_node_id), None)
                        if source_node:
                            finding = RiskFinding(
                                risk_id=self.generate_risk_id(app.application_id, edge.edge_id),
                                application_id=app.application_id,
                                category=self.category,
                                risk_type=self.risk_type,
                                severity=Severity.MEDIUM,
                                title="External dependency",
                                description=f"{source_node.name} depends on external service {node.name}.",
                                target_type="edge",
                                target_id=edge.edge_id,
                                confidence=0.9,
                                evidence=[Evidence(source="architecture", type="graph_relationship", detail=f"{source_node.name} \u2192 {node.name}")],
                                indicators=[]
                            )
                            findings.append(finding)
                
        return findings
