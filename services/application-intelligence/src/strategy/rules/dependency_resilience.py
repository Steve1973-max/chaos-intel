from typing import List
from ..base import StrategyRule
from ...models.application import ApplicationModel
from ...models.test_candidate import TestCandidate
from ..priority import calculate_priority
from ...models.technology import Evidence

class DependencyResilienceStrategyRule(StrategyRule):
    @property
    def rule_id(self) -> str:
        return "strat-dep-res"

    def generate(self, app: ApplicationModel) -> List[TestCandidate]:
        candidates = []
        
        for risk in app.risks:
            if risk.risk_type in ("critical_dependency", "dependency_concentration"):
                pri = calculate_priority(risk.severity, risk.confidence, is_central=True)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "dependency_resilience", risk.target_id),
                    application_id=app.application_id,
                    target_type=risk.target_type,
                    target_id=risk.target_id,
                    test_type="dependency_resilience",
                    title="Critical Dependency Degradation",
                    hypothesis=f"If the critical dependency ({risk.target_id}) becomes unavailable or degraded, upstream services may experience cascading failure or elevated latency.",
                    reason="Validate application behavior when the critical dependency is unavailable or degraded.",
                    expected_failure_mode="cascading failure",
                    priority=pri,
                    confidence=risk.confidence,
                    prerequisites=["observability enabled"],
                    evidence=list(risk.evidence),
                    related_risk_ids=[risk.risk_id],
                    suggested_observations=["error rate", "dependency availability"]
                )
                candidates.append(cand)
                
            elif risk.risk_type == "unresolved_dependency":
                pri = calculate_priority(risk.severity, risk.confidence)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "dependency_resilience", risk.target_id),
                    application_id=app.application_id,
                    target_type=risk.target_type,
                    target_id=risk.target_id,
                    test_type="dependency_resilience",
                    title="Unresolved Dependency Resilience",
                    hypothesis=f"If the unresolved dependency cannot be reached, the dependent service ({risk.target_id}) may experience request failures.",
                    reason="Validate behavior around an unresolved dependency.",
                    expected_failure_mode="timeout",
                    priority=pri,
                    confidence=risk.confidence,
                    prerequisites=[],
                    evidence=list(risk.evidence),
                    related_risk_ids=[risk.risk_id],
                    suggested_observations=["error rate"]
                )
                candidates.append(cand)
                
        # Non-risk candidate: any database dependency
        for dep in app.dependencies:
            if dep.dependency_type in ("database", "postgres", "mysql", "mongodb"):
                # Avoid generating if a risk already covered it (we will rely on deduplication later or just emit)
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "dependency_resilience", dep.name),
                    application_id=app.application_id,
                    target_type="dependency",
                    target_id=dep.name,
                    test_type="dependency_resilience",
                    title="Database Dependency Resilience",
                    hypothesis=f"If {dep.name} is slow, dependent services may experience degraded throughput.",
                    reason="Validate resilience against database degradation.",
                    expected_failure_mode="degraded throughput",
                    priority="medium",
                    confidence=0.8,
                    prerequisites=["observability enabled"],
                    evidence=list(dep.evidence),
                    related_risk_ids=[],
                    suggested_observations=["p95 latency"]
                )
                candidates.append(cand)
                
        # Non-risk candidate: message broker
        for dep in app.dependencies:
            if dep.dependency_type in ("message_broker", "kafka", "rabbitmq"):
                cand = TestCandidate(
                    candidate_id=self.generate_candidate_id(app.application_id, "dependency_resilience", dep.name),
                    application_id=app.application_id,
                    target_type="dependency",
                    target_id=dep.name,
                    test_type="dependency_resilience",
                    title="Message Queue Resilience",
                    hypothesis=f"If {dep.name} rejects messages, workers may experience queue backlog.",
                    reason="Validate resilience of message queue consumers/producers.",
                    expected_failure_mode="queue backlog",
                    priority="medium",
                    confidence=0.8,
                    prerequisites=["test traffic available"],
                    evidence=list(dep.evidence),
                    related_risk_ids=[],
                    suggested_observations=["queue depth"]
                )
                candidates.append(cand)

        return candidates
