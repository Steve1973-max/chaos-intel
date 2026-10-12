from typing import List
from ..base import StrategyRule
from ...models.application import ApplicationModel
from ...models.test_candidate import TestCandidate
from ..priority import calculate_priority

class ApiResilienceStrategyRule(StrategyRule):
    @property
    def rule_id(self) -> str:
        return "strat-api"

    def generate(self, app: ApplicationModel) -> List[TestCandidate]:
        candidates = []
        
        for risk in app.risks:
            if risk.risk_type == "api_concentration":
                pri = calculate_priority(risk.severity, risk.confidence)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "api_resilience", risk.target_id),
                    application_id=app.application_id,
                    target_type=risk.target_type,
                    target_id=risk.target_id,
                    test_type="api_resilience",
                    title="Concentrated API Surface Validation",
                    hypothesis=f"If the service hosting the majority of APIs ({risk.target_id}) experiences load, it may degrade application-wide API responses.",
                    reason="Validate resilience of the service hosting the majority of discovered APIs.",
                    expected_failure_mode="degraded throughput",
                    priority=pri,
                    confidence=risk.confidence,
                    prerequisites=["test traffic available"],
                    evidence=list(risk.evidence),
                    related_risk_ids=[risk.risk_id],
                    suggested_observations=["request success rate"]
                )
                candidates.append(cand)
                
            elif risk.risk_type == "explicitly_unauthenticated_api":
                pri = calculate_priority(risk.severity, risk.confidence)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "api_resilience", risk.target_id),
                    application_id=app.application_id,
                    target_type=risk.target_type,
                    target_id=risk.target_id,
                    test_type="api_resilience",
                    title="Unauthenticated API Availability",
                    hypothesis=f"If the unauthenticated endpoint receives excessive requests, it may cause resource exhaustion.",
                    reason="Validate availability and error handling of the explicitly unauthenticated endpoint.",
                    expected_failure_mode="elevated latency",
                    priority=pri,
                    confidence=risk.confidence,
                    prerequisites=[],
                    evidence=list(risk.evidence),
                    related_risk_ids=[risk.risk_id],
                    suggested_observations=["error rate"]
                )
                candidates.append(cand)
                
        return candidates
