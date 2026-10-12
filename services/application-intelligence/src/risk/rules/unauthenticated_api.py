from typing import List
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class UnauthenticatedApiRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-unauth-api"

    @property
    def category(self) -> str:
        return "api"
        
    @property
    def risk_type(self) -> str:
        return "explicitly_unauthenticated_api"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        
        for api in app.apis:
            if api.auth_required is False:
                service = next((s for s in app.services if s.service_id == api.service_id), None)
                service_name = service.name if service else api.service_id
                
                finding = RiskFinding(
                    risk_id=self.generate_risk_id(app.application_id, api.api_id),
                    application_id=app.application_id,
                    category=self.category,
                    risk_type=self.risk_type,
                    severity=Severity.MEDIUM,
                    title="Explicitly unauthenticated API",
                    description=f"The endpoint {api.method} {api.path} on {service_name} explicitly requires no authentication.",
                    target_type="api",
                    target_id=api.api_id,
                    confidence=api.confidence,
                    evidence=list(api.evidence),
                    indicators=[]
                )
                findings.append(finding)
                
        return findings
