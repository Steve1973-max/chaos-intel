from typing import List
from ..base import StrategyRule
from ...models.application import ApplicationModel
from ...models.test_candidate import TestCandidate
from ..priority import calculate_priority

class CyclicDependencyStrategyRule(StrategyRule):
    @property
    def rule_id(self) -> str:
        return "strat-cycle"

    def generate(self, app: ApplicationModel) -> List[TestCandidate]:
        candidates = []
        
        for risk in app.risks:
            if risk.risk_type == "cyclic_dependency":
                pri = calculate_priority(risk.severity, risk.confidence)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "workflow_resilience", risk.target_id),
                    application_id=app.application_id,
                    target_type=risk.target_type,
                    target_id=risk.target_id,
                    test_type="workflow_resilience",
                    title="Cyclic Dependency Validation",
                    hypothesis=f"If a component in the cycle degrades, it may cause a cascading failure throughout the cycle.",
                    reason="Validate whether cyclic service relationships can degrade safely without cascading failure.",
                    expected_failure_mode="cascading failure",
                    priority=pri,
                    confidence=risk.confidence,
                    prerequisites=["observability enabled"],
                    evidence=list(risk.evidence),
                    related_risk_ids=[risk.risk_id],
                    suggested_observations=["error rate"]
                )
                candidates.append(cand)
                
        return candidates
