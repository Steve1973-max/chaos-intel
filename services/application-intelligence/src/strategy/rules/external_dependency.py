from typing import List
from ..base import StrategyRule
from ...models.application import ApplicationModel
from ...models.test_candidate import TestCandidate
from ..priority import calculate_priority

class ExternalDependencyStrategyRule(StrategyRule):
    @property
    def rule_id(self) -> str:
        return "strat-ext-dep"

    def generate(self, app: ApplicationModel) -> List[TestCandidate]:
        candidates = []
        
        # Risk-based candidates
        for risk in app.risks:
            if risk.risk_type == "external_dependency":
                pri = calculate_priority(risk.severity, risk.confidence)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "dependency_resilience", risk.target_id),
                    application_id=app.application_id,
                    target_type=risk.target_type,
                    target_id=risk.target_id,
                    test_type="dependency_resilience",
                    title="External API Resilience",
                    hypothesis=f"If the external API is unavailable or slow, dependent workflows may experience elevated latency or timeouts.",
                    reason="Validate behavior when the external API is unavailable or slow.",
                    expected_failure_mode="elevated latency",
                    priority=pri,
                    confidence=risk.confidence,
                    prerequisites=[],
                    evidence=list(risk.evidence),
                    related_risk_ids=[risk.risk_id],
                    suggested_observations=["p95 latency", "error rate"]
                )
                candidates.append(cand)
                
        # Non-risk based external API candidate
        for dep in app.dependencies:
            if dep.dependency_type == "external_api":
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "dependency_resilience", dep.name),
                    application_id=app.application_id,
                    target_type="dependency",
                    target_id=dep.name,
                    test_type="dependency_resilience",
                    title="External API Degradation",
                    hypothesis=f"If {dep.name} exhibits high latency, upstream services will experience timeout.",
                    reason="Validate behavior during external API degradation.",
                    expected_failure_mode="timeout",
                    priority="low",
                    confidence=0.8,
                    prerequisites=[],
                    evidence=list(dep.evidence),
                    related_risk_ids=[],
                    suggested_observations=["p95 latency"]
                )
                candidates.append(cand)
                
        return candidates
