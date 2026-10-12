from typing import List
from ..base import RiskRule
from ...models.application import ApplicationModel
from ...models.risk import RiskFinding
from ..severity import Severity
from ...models.technology import Evidence

class ApiConcentrationRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "rule-api-conc"

    @property
    def category(self) -> str:
        return "api"
        
    @property
    def risk_type(self) -> str:
        return "api_concentration"

    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        findings = []
        total_apis = len(app.apis)
        
        if total_apis < 10:
            return findings
            
        api_counts = {}
        for api in app.apis:
            api_counts[api.service_id] = api_counts.get(api.service_id, 0) + 1
            
        for service_id, count in api_counts.items():
            proportion = count / total_apis
            if proportion > 0.5:
                service = next((s for s in app.services if s.service_id == service_id), None)
                if service:
                    finding = RiskFinding(
                        risk_id=self.generate_risk_id(app.application_id, service_id),
                        application_id=app.application_id,
                        category=self.category,
                        risk_type=self.risk_type,
                        severity=Severity.INFO,
                        title="API surface concentration",
                        description=f"{service.name} exposes a large proportion of the application's discovered APIs ({count}/{total_apis}).",
                        target_type="service",
                        target_id=service_id,
                        confidence=0.95,
                        evidence=[Evidence(source="api_inventory", type="statistical", detail=f"{proportion*100:.1f}% of APIs")],
                        indicators=[{"metric": "api_count", "value": count}, {"metric": "api_proportion", "value": proportion}]
                    )
                    findings.append(finding)
                
        return findings
