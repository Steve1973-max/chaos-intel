from typing import List
from ..base import StrategyRule
from ...models.application import ApplicationModel
from ...models.test_candidate import TestCandidate
from ..priority import calculate_priority

class AvailabilityStrategyRule(StrategyRule):
    @property
    def rule_id(self) -> str:
        return "strat-avail"

    def generate(self, app: ApplicationModel) -> List[TestCandidate]:
        candidates = []
        
        for risk in app.risks:
            if risk.risk_type == "availability_concentration":
                pri = calculate_priority(risk.severity, risk.confidence, is_central=True)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "availability", risk.target_id),
                    application_id=app.application_id,
                    target_type=risk.target_type,
                    target_id=risk.target_id,
                    test_type="availability",
                    title="Infrastructure Availability Validation",
                    hypothesis=f"If the concentrated infrastructure dependency ({risk.target_id}) becomes unavailable, dependent services may experience request failures or degraded availability.",
                    reason="Validate service behavior when a concentrated infrastructure dependency becomes unavailable.",
                    expected_failure_mode="request failure",
                    priority=pri,
                    confidence=risk.confidence,
                    prerequisites=["service dependency confirmed", "disposable environment"],
                    evidence=list(risk.evidence),
                    related_risk_ids=[risk.risk_id],
                    suggested_observations=["request success rate", "error rate"]
                )
                candidates.append(cand)
                
            elif risk.risk_type == "single_point_of_failure":
                pri = calculate_priority(risk.severity, risk.confidence)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "failover", risk.target_id),
                    application_id=app.application_id,
                    target_type=risk.target_type,
                    target_id=risk.target_id,
                    test_type="failover",
                    title="Central Service Failover Validation",
                    hypothesis=f"If the central service ({risk.target_id}) is unavailable, critical traffic may fail without successful failover.",
                    reason="Validate whether critical traffic can continue when the central service is unavailable.",
                    expected_failure_mode="unavailable dependency",
                    priority=pri,
                    confidence=risk.confidence,
                    prerequisites=["test traffic available"],
                    evidence=list(risk.evidence),
                    related_risk_ids=[risk.risk_id],
                    suggested_observations=["p95 latency", "request success rate"]
                )
                candidates.append(cand)
                
        return candidates
