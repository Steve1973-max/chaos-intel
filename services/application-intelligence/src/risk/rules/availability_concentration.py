from typing import List
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class AvailabilityConcentrationRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-avail-conc"

    @property
    def category(self) -> str:
        return "availability"
        
    @property
    def risk_type(self) -> str:
        return "availability_concentration"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        
        infra_types = {"postgres", "redis", "kafka", "rabbitmq", "database", "cache", "message_broker"}
        
        infra_nodes = [n for n in app.architecture.nodes if n.node_type in infra_types]
        
        incoming = {}
        for edge in app.architecture.edges:
            incoming[edge.target_node_id] = incoming.get(edge.target_node_id, 0) + 1
            
        # Count nodes of each infra type
        type_counts = {}
        for node in infra_nodes:
            type_counts[node.node_type] = type_counts.get(node.node_type, 0) + 1
            
        for node in infra_nodes:
            # If it's the only one of its kind and serves multiple services
            if type_counts[node.node_type] == 1:
                inc_count = incoming.get(node.node_id, 0)
                if inc_count > 1:
                    finding = RiskFinding(
                        risk_id=self.generate_risk_id(app.application_id, node.node_id),
                        application_id=app.application_id,
                        category=self.category,
                        risk_type=self.risk_type,
                        severity=Severity.HIGH,
                        title="Potential availability concentration",
                        description=f"A single {node.node_type} instance ({node.name}) serves {inc_count} services.",
                        target_type="node",
                        target_id=node.node_id,
                        confidence=0.85,
                        evidence=[Evidence(source="architecture", type="graph_analysis", detail=f"1 {node.node_type} instance serving {inc_count} upstream nodes")],
                        indicators=[{"metric": "incoming_dependency_count", "value": inc_count}]
                    )
                    findings.append(finding)
                
        return findings
