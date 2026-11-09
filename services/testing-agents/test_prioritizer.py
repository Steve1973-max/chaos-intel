from typing import Dict, List, Optional
try:
    from .agent_registry import AgentCapabilities, DeterministicBaselineProvider, IntelligenceProvider
    from .schemas import (
        ApplicationModel,
        InvalidInputError,
        PriorityBreakdown,
        RiskFinding,
        TestCase,
    )
except ImportError:
    from agent_registry import AgentCapabilities, DeterministicBaselineProvider, IntelligenceProvider  # type: ignore[no-redef]
    from schemas import (  # type: ignore[no-redef]
        ApplicationModel,
        InvalidInputError,
        PriorityBreakdown,
        RiskFinding,
        TestCase,
    )


SEVERITY_WEIGHTS: Dict[str, float] = {
    "info": 0.15,
    "low": 0.30,
    "medium": 0.55,
    "high": 0.80,
    "critical": 1.00,
}

PRIORITY_TO_SEVERITY: Dict[str, float] = {
    "low": 0.30,
    "medium": 0.55,
    "high": 0.80,
    "critical": 1.00,
}


class TestPrioritizer:
    """
    Ranks generated test cases using:
    1. Risk score (35%)
    2. Severity score (30%)
    3. Dependency criticality (20%)
    4. Confidence score (15%)

    Produces explainable PriorityBreakdown records and deterministic rankings.
    """

    __test__ = False

    def __init__(self, provider: Optional[IntelligenceProvider] = None) -> None:
        self.provider: IntelligenceProvider = provider or DeterministicBaselineProvider()

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            agent_id="test-prioritizer-v1",
            agent_type="test_prioritizer",
            version="1.0.0",
            deterministic=True,
            can_authorize_execution=False,
            supported_tasks=["risk_based_prioritization", "dependency_criticality_scoring", "explainable_ranking"],
        )

    def _compute_dependency_criticality(self, test_case: TestCase, app: Optional[ApplicationModel]) -> tuple[float, List[str]]:
        factors: List[str] = []
        if app is None:
            base = 0.65 if test_case.test_type in ("dependency_resilience", "failover", "workflow_resilience") else 0.45
            factors.append(f"Baseline target criticality ({base:.2f}) without full architecture graph")
            return round(base, 4), factors

        target_id = test_case.target_id
        in_degree = 0
        out_degree = 0

        # Count upstream callers in dependencies
        for dep in app.dependencies:
            if dep.target_service_id == target_id or dep.name == target_id or (
                f"{dep.source_service_id}->{dep.target_service_id or dep.name}" == target_id
            ):
                in_degree += 1
            if dep.source_service_id == target_id:
                out_degree += 1

        # Also inspect architecture graph edges
        if app.architecture and app.architecture.edges:
            for edge in app.architecture.edges:
                if edge.target_node_id == target_id or edge.edge_id == target_id:
                    in_degree += 1
                if edge.source_node_id == target_id:
                    out_degree += 1

        score = 0.35
        if in_degree > 0:
            inbound_boost = min(0.40, in_degree * 0.12)
            score += inbound_boost
            factors.append(f"Inbound dependency fan-in={in_degree} (+{inbound_boost:.2f})")

        if out_degree > 0:
            outbound_boost = min(0.15, out_degree * 0.05)
            score += outbound_boost
            factors.append(f"Outbound dependency fan-out={out_degree} (+{outbound_boost:.2f})")

        # Stateful or foundational infrastructure role boost
        for svc in app.services:
            if svc.service_id == target_id or svc.name == target_id:
                if svc.type in ("database", "message_broker", "cache", "gateway"):
                    score += 0.20
                    factors.append(f"Critical service role='{svc.type}' (+0.20)")
                elif svc.type == "backend":
                    score += 0.10
                    factors.append("Core backend service role (+0.10)")
                break

        if test_case.target_type == "workflow" or test_case.test_type == "workflow_resilience":
            score += 0.25
            factors.append("Multi-hop workflow resilience path (+0.25)")

        bounded = round(min(1.0, max(0.0, score)), 4)
        if not factors:
            factors.append(f"Standard architectural component criticality ({bounded:.2f})")
        return bounded, factors

    def _compute_risk_and_severity(
        self, test_case: TestCase, app: Optional[ApplicationModel]
    ) -> tuple[float, float, List[str]]:
        factors: List[str] = []
        matched_risks: List[RiskFinding] = []

        if app is not None and app.risks:
            risk_id_set = set(test_case.related_risk_ids or [])
            for risk in app.risks:
                if risk.risk_id in risk_id_set or (
                    risk.target_type == test_case.target_type and risk.target_id == test_case.target_id
                ):
                    matched_risks.append(risk)

        base_severity = PRIORITY_TO_SEVERITY.get(test_case.priority, 0.55)
        if matched_risks:
            max_risk_sev = max(SEVERITY_WEIGHTS.get(r.severity.lower(), 0.30) for r in matched_risks)
            severity_score = round(max(base_severity, max_risk_sev), 4)
            # Risk score combines max severity with multi-risk density and average risk confidence
            avg_risk_conf = sum(r.confidence for r in matched_risks) / len(matched_risks)
            density_bonus = min(0.20, (len(matched_risks) - 1) * 0.08)
            risk_score = round(min(1.0, (max_risk_sev * 0.75) + (avg_risk_conf * 0.15) + density_bonus), 4)
            risk_ids_str = ", ".join(sorted(r.risk_id for r in matched_risks))
            factors.append(
                f"Linked to {len(matched_risks)} risk finding(s) [{risk_ids_str}] (severity_score={severity_score:.2f}, risk_score={risk_score:.2f})"
            )
        else:
            severity_score = round(base_severity, 4)
            risk_score = round(min(1.0, base_severity * 0.85), 4)
            factors.append(
                f"Derived from candidate priority='{test_case.priority}' (severity_score={severity_score:.2f}, risk_score={risk_score:.2f})"
            )

        return risk_score, severity_score, factors

    @staticmethod
    def _score_to_band(total_score: float) -> str:
        if total_score >= 80.0:
            return "critical"
        if total_score >= 62.0:
            return "high"
        if total_score >= 40.0:
            return "medium"
        return "low"

    def score_test_case(self, test_case: TestCase, app: Optional[ApplicationModel] = None) -> PriorityBreakdown:
        if test_case is None or not isinstance(test_case, TestCase):
            raise InvalidInputError("score_test_case requires a valid TestCase instance.")

        risk_score, severity_score, risk_factors = self._compute_risk_and_severity(test_case, app)
        dep_score, dep_factors = self._compute_dependency_criticality(test_case, app)
        conf_score = round(float(test_case.confidence), 4)

        raw_total = (
            (risk_score * 0.35)
            + (severity_score * 0.30)
            + (dep_score * 0.20)
            + (conf_score * 0.15)
        ) * 100.0
        total_score = round(min(100.0, max(0.0, raw_total)), 2)
        band = self._score_to_band(total_score)

        factors = risk_factors + dep_factors + [f"Detection confidence={conf_score:.2f}"]
        preliminary = PriorityBreakdown(
            total_score=total_score,
            priority_band=band,  # type: ignore[arg-type]
            risk_score=risk_score,
            severity_score=severity_score,
            dependency_criticality_score=dep_score,
            confidence_score=conf_score,
            explanation="Pending explanation",
            factors=factors,
        )
        preliminary.explanation = self.provider.explain_priority(test_case.title, preliminary)
        return preliminary

    def prioritize(
        self, test_cases: List[TestCase], app: Optional[ApplicationModel] = None
    ) -> List[TestCase]:
        """
        Scores, updates priority bands, deterministically ranks, and returns a new list of TestCases.
        """
        if test_cases is None or not isinstance(test_cases, list):
            raise InvalidInputError("prioritize requires a list of TestCase instances.")

        scored_cases: List[TestCase] = []
        for tc in test_cases:
            if not isinstance(tc, TestCase):
                raise InvalidInputError("All elements passed to prioritize must be TestCase instances.")
            updated = tc.model_copy(deep=True)
            breakdown = self.score_test_case(updated, app)
            updated.priority_breakdown = breakdown
            updated.priority_score = breakdown.total_score
            updated.priority = breakdown.priority_band
            scored_cases.append(updated)

        # Deterministic sort: highest priority_score, then highest confidence, then lexicographical test_case_id
        ranked = sorted(
            scored_cases,
            key=lambda c: (-c.priority_score, -c.confidence, c.test_case_id),
        )
        for idx, tc in enumerate(ranked, start=1):
            tc.rank = idx

        return ranked
