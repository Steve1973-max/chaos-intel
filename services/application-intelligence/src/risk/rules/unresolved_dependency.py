from typing import List
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class UnresolvedDependencyRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-unres-dep"

    @property
    def category(self) -> str:
        return "dependency"
        
    @property
    def risk_type(self) -> str:
        return "unresolved_dependency"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        
        for dep in app.dependencies:
            if not dep.target_service_id and dep.dependency_type == "unknown":
                # Only if explicitly marked unresolved or unknown
                source_service = next((s for s in app.services if s.service_id == dep.source_service_id), None)
                if source_service:
                    finding = RiskFinding(
                        risk_id=self.generate_risk_id(app.application_id, dep.source_service_id + "-" + dep.name),
                        application_id=app.application_id,
                        category=self.category,
                        risk_type=self.risk_type,
                        severity=Severity.LOW,
                        title="Unresolved dependency",
                        description=f"{source_service.name} depends on '{dep.name}', but it could not be resolved to a known service or infrastructure.",
                        target_type="service",
                        target_id=source_service.service_id,
                        confidence=0.8,
                        evidence=list(dep.evidence),
                        indicators=[]
                    )
                    findings.append(finding)
                
        return findings
