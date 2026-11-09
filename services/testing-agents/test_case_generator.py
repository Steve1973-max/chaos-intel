import hashlib
from typing import Dict, List, Optional, Tuple
try:
    from .agent_registry import AgentCapabilities, DeterministicBaselineProvider, IntelligenceProvider, TestSuggestion
    from .evidence_collector import EvidenceCollector
    from .test_prioritizer import TestPrioritizer
    from .schemas import (
        SCHEMA_VERSION,
        VALID_PRIORITIES,
        VALID_TEST_TYPES,
        ApplicationModel,
        Evidence,
        EvidenceTraceabilityError,
        InvalidInputError,
        PriorityBreakdown,
        TestCandidate,
        TestCase,
        TestStep,
    )
except ImportError:
    from agent_registry import AgentCapabilities, DeterministicBaselineProvider, IntelligenceProvider, TestSuggestion  # type: ignore[no-redef]
    from evidence_collector import EvidenceCollector  # type: ignore[no-redef]
    from test_prioritizer import TestPrioritizer  # type: ignore[no-redef]
    from schemas import (  # type: ignore[no-redef]
        SCHEMA_VERSION,
        VALID_PRIORITIES,
        VALID_TEST_TYPES,
        ApplicationModel,
        Evidence,
        EvidenceTraceabilityError,
        InvalidInputError,
        PriorityBreakdown,
        TestCandidate,
        TestCase,
        TestStep,
    )


class TestCaseGenerator:
    """
    Generates structured, explainable, and deduplicated TestCases from deterministic
    TestCandidates and optional evidence-backed IntelligenceProvider suggestions.
    """

    __test__ = False

    def __init__(
        self,
        evidence_collector: Optional[EvidenceCollector] = None,
        prioritizer: Optional[TestPrioritizer] = None,
        provider: Optional[IntelligenceProvider] = None,
    ) -> None:
        self.evidence_collector = evidence_collector or EvidenceCollector()
        self.provider: IntelligenceProvider = provider or DeterministicBaselineProvider()
        self.prioritizer = prioritizer or TestPrioritizer(provider=self.provider)

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            agent_id="test-case-generator-v1",
            agent_type="test_case_generator",
            version="1.0.0",
            deterministic=self.provider.is_deterministic,
            can_authorize_execution=False,
            supported_tasks=[
                "candidate_to_testcase_conversion",
                "duplicate_detection_and_merging",
                "step_and_assertion_synthesis",
            ],
        )

    @staticmethod
    def compute_test_case_id(application_id: str, test_type: str, target_type: str, target_id: str) -> str:
        canonical = f"{application_id.strip()}::{test_type.strip()}::{target_type.strip()}::{target_id.strip()}"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        return f"tc-{digest}"

    @staticmethod
    def _resolve_target_name(candidate: TestCandidate, app: Optional[ApplicationModel]) -> str:
        if app is not None:
            for svc in app.services:
                if svc.service_id == candidate.target_id:
                    return svc.name
            for api in app.apis:
                if api.api_id == candidate.target_id:
                    return f"{api.method} {api.path}"
            if app.architecture:
                for node in app.architecture.nodes:
                    if node.node_id == candidate.target_id:
                        return node.name
        return candidate.target_id

    @staticmethod
    def _resolve_related_experiments(candidate: TestCandidate, app: Optional[ApplicationModel]) -> List[str]:
        if app is None or not app.experiments:
            return []
        matched: List[str] = []
        for exp in app.experiments:
            if candidate.candidate_id in (exp.candidate_ids or []) or (
                exp.target.type == candidate.target_type and exp.target.id == candidate.target_id
            ):
                if exp.experiment_id not in matched:
                    matched.append(exp.experiment_id)
        return sorted(matched)

    @staticmethod
    def _build_steps(candidate: TestCandidate, target_name: str) -> List[TestStep]:
        observations = candidate.suggested_observations or [
            f"Service health and error rate metrics for {target_name}",
            f"Latency p95/p99 and saturation indicators for {target_name}",
        ]
        obs_summary = "; ".join(observations)
        return [
            TestStep(
                step_number=1,
                phase="steady_state_check",
                action=f"Verify baseline steady-state health and readiness of '{target_name}' ({candidate.target_id}) prior to test.",
                expected_observation=f"Target '{target_name}' meets baseline SLOs with zero active critical alerts.",
            ),
            TestStep(
                step_number=2,
                phase="stimulus_plan",
                action=(
                    f"Prepare declarative '{candidate.test_type}' resilience stimulus specification targeting "
                    f"'{target_name}' ({candidate.target_type}:{candidate.target_id}) for Safety & Policy Engine evaluation."
                ),
                expected_observation=(
                    f"Declarative fault plan is validated; expected failure mode under test: {candidate.expected_failure_mode}"
                ),
            ),
            TestStep(
                step_number=3,
                phase="observation",
                action=f"Monitor telemetry and resilience indicators during simulated degradation: {obs_summary}.",
                expected_observation=f"Hypothesis validated: {candidate.hypothesis}",
            ),
            TestStep(
                step_number=4,
                phase="recovery_verification",
                action=f"Verify clean rollback and steady-state restoration for '{target_name}' after stimulus window.",
                expected_observation=f"'{target_name}' returns to baseline steady state within configured recovery SLA.",
            ),
        ]

    @staticmethod
    def _build_assertions(candidate: TestCandidate, target_name: str) -> List[str]:
        assertions = [
            f"Hypothesis holds: {candidate.hypothesis}",
            f"No unhandled cascading failure beyond '{target_name}' ({candidate.expected_failure_mode}).",
        ]
        for obs in candidate.suggested_observations or []:
            entry = f"Telemetry assertion verified: {obs}"
            if entry not in assertions:
                assertions.append(entry)
        assertions.append(f"Post-test steady-state recovery verified for '{target_name}'.")
        return assertions

    def from_candidate(
        self,
        candidate: TestCandidate,
        app: Optional[ApplicationModel] = None,
        generation_source: str = "deterministic_candidate",
    ) -> TestCase:
        if candidate is None or not isinstance(candidate, TestCandidate):
            raise InvalidInputError("from_candidate requires a valid TestCandidate instance.")

        if not candidate.application_id or not candidate.application_id.strip():
            raise InvalidInputError("TestCandidate.application_id must be a non-empty string.")
        if not candidate.target_id or not candidate.target_id.strip():
            raise InvalidInputError("TestCandidate.target_id must be a non-empty string.")
        if candidate.test_type not in VALID_TEST_TYPES:
            raise InvalidInputError(f"Unsupported test_type '{candidate.test_type}'.")
        if candidate.priority not in VALID_PRIORITIES:
            raise InvalidInputError(f"Unsupported priority '{candidate.priority}'.")

        evidence, evidence_reasoning = self.evidence_collector.collect_for_candidate(candidate, app)
        target_name = self._resolve_target_name(candidate, app)
        related_experiments = self._resolve_related_experiments(candidate, app)
        steps = self._build_steps(candidate, target_name)
        assertions = self._build_assertions(candidate, target_name)

        preconditions = list(candidate.prerequisites or [])
        default_precondition = "Safety & Policy Engine approval and dry-run preflight verification completed."
        if default_precondition not in preconditions:
            preconditions.insert(0, default_precondition)

        test_case_id = self.compute_test_case_id(
            candidate.application_id,
            candidate.test_type,
            candidate.target_type,
            candidate.target_id,
        )

        placeholder_breakdown = PriorityBreakdown(
            total_score=50.0,
            priority_band=candidate.priority,  # type: ignore[arg-type]
            risk_score=0.5,
            severity_score=0.5,
            dependency_criticality_score=0.5,
            confidence_score=round(float(candidate.confidence), 4),
            explanation="Initial priority prior to full portfolio ranking.",
            factors=["Initial candidate conversion"],
        )

        tc = TestCase(
            test_case_id=test_case_id,
            schema_version=SCHEMA_VERSION,
            application_id=candidate.application_id,
            candidate_id=candidate.candidate_id,
            target_type=candidate.target_type,
            target_id=candidate.target_id,
            target_name=target_name,
            test_type=candidate.test_type,  # type: ignore[arg-type]
            title=candidate.title,
            hypothesis=candidate.hypothesis,
            reason=candidate.reason,
            expected_failure_mode=candidate.expected_failure_mode,
            status="draft" if candidate.confidence >= 0.6 else "requires_review",
            mode="plan_only",
            execution_authorized=False,
            requires_safety_decision=True,
            priority=candidate.priority,  # type: ignore[arg-type]
            priority_score=50.0,
            rank=None,
            priority_breakdown=placeholder_breakdown,
            confidence=round(float(candidate.confidence), 4),
            preconditions=preconditions,
            test_steps=steps,
            assertions=assertions,
            required_capabilities=sorted(set(candidate.required_capabilities or [])),
            related_risk_ids=sorted(set(candidate.related_risk_ids or [])),
            related_experiment_ids=related_experiments,
            evidence=evidence,
            evidence_reasoning=evidence_reasoning,
            generation_source=generation_source,  # type: ignore[arg-type]
            provider_id=self.provider.provider_id,
            metadata={
                "merged_candidate_ids": [candidate.candidate_id],
                **(candidate.metadata or {}),
            },
        )

        # Compute full explainable priority breakdown immediately
        breakdown = self.prioritizer.score_test_case(tc, app)
        tc.priority_breakdown = breakdown
        tc.priority_score = breakdown.total_score
        tc.priority = breakdown.priority_band
        return tc

    def suggestion_to_candidate(self, suggestion: TestSuggestion, application_id: str) -> TestCandidate:
        if not isinstance(suggestion, TestSuggestion):
            raise InvalidInputError("suggestion must be a TestSuggestion instance.")
        digest = hashlib.sha256(
            f"{application_id}::{suggestion.test_type}::{suggestion.target_type}::{suggestion.target_id}".encode("utf-8")
        ).hexdigest()[:8]
        return TestCandidate(
            candidate_id=f"cand-ai-{digest}",
            application_id=application_id,
            target_type=suggestion.target_type,
            target_id=suggestion.target_id,
            test_type=suggestion.test_type,
            title=suggestion.title,
            hypothesis=suggestion.hypothesis,
            reason=suggestion.reason,
            expected_failure_mode=suggestion.expected_failure_mode,
            priority=suggestion.priority if suggestion.priority in VALID_PRIORITIES else "medium",
            confidence=suggestion.confidence,
            prerequisites=suggestion.prerequisites,
            evidence=suggestion.evidence,
            related_risk_ids=suggestion.related_risk_ids,
            required_capabilities=["fault_injection", "telemetry_observation"],
            suggested_observations=suggestion.suggested_observations,
            metadata={"suggested_by": self.provider.provider_id},
        )

    def deduplicate_test_cases(self, test_cases: List[TestCase], app: Optional[ApplicationModel] = None) -> Tuple[List[TestCase], int]:
        """
        Deduplicates test cases by semantic target key (application_id, test_type, target_type, target_id).
        Merges evidence, risk IDs, experiment IDs, preconditions, and capabilities deterministically.
        Returns (deduplicated_cases, duplicates_removed_count).
        """
        by_key: Dict[Tuple[str, str, str, str], TestCase] = {}
        duplicates_removed = 0
        pri_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}

        for tc in test_cases:
            key = (tc.application_id, tc.test_type, tc.target_type, tc.target_id)
            if key not in by_key:
                by_key[key] = tc.model_copy(deep=True)
            else:
                duplicates_removed += 1
                existing = by_key[key]

                # Merge evidence deterministically
                existing.evidence = self.evidence_collector.deduplicate_evidence(
                    list(existing.evidence) + list(tc.evidence)
                )

                # Merge related_risk_ids, related_experiment_ids, required_capabilities, preconditions, assertions
                existing.related_risk_ids = sorted(set(existing.related_risk_ids) | set(tc.related_risk_ids))
                existing.related_experiment_ids = sorted(
                    set(existing.related_experiment_ids) | set(tc.related_experiment_ids)
                )
                existing.required_capabilities = sorted(
                    set(existing.required_capabilities) | set(tc.required_capabilities)
                )
                for pre in tc.preconditions:
                    if pre not in existing.preconditions:
                        existing.preconditions.append(pre)
                for assertion in tc.assertions:
                    if assertion not in existing.assertions:
                        existing.assertions.append(assertion)

                # Track merged candidate IDs
                merged_ids = list(existing.metadata.get("merged_candidate_ids", [existing.candidate_id]))
                for cid in tc.metadata.get("merged_candidate_ids", [tc.candidate_id]):
                    if cid not in merged_ids:
                        merged_ids.append(cid)
                existing.metadata["merged_candidate_ids"] = sorted(merged_ids)

                # Retain highest confidence and priority
                existing.confidence = round(max(existing.confidence, tc.confidence), 4)
                if pri_rank.get(tc.priority, 1) > pri_rank.get(existing.priority, 1):
                    existing.priority = tc.priority

                # Re-score after merging risk and confidence evidence
                breakdown = self.prioritizer.score_test_case(existing, app)
                existing.priority_breakdown = breakdown
                existing.priority_score = breakdown.total_score
                existing.priority = breakdown.priority_band

        deduped_list = sorted(by_key.values(), key=lambda c: c.test_case_id)
        return deduped_list, duplicates_removed

    def generate(
        self,
        candidates: List[TestCandidate],
        app: Optional[ApplicationModel] = None,
        include_provider_suggestions: bool = True,
    ) -> Tuple[List[TestCase], int]:
        """
        Generates structured, deduplicated test cases from deterministic candidates
        and optional IntelligenceProvider suggestions.
        Returns (test_cases, duplicates_removed_count).
        """
        if candidates is None or not isinstance(candidates, list):
            raise InvalidInputError("generate requires a list of TestCandidate instances.")

        raw_cases: List[TestCase] = []
        for cand in candidates:
            raw_cases.append(self.from_candidate(cand, app=app, generation_source="deterministic_candidate"))

        if include_provider_suggestions and app is not None:
            suggestions = self.provider.suggest_test_cases(app)
            for suggestion in suggestions:
                synth_cand = self.suggestion_to_candidate(suggestion, app.application_id)
                source_tag = "ai_suggestion" if not self.provider.is_deterministic else "coverage_gap_synthesis"
                raw_cases.append(self.from_candidate(synth_cand, app=app, generation_source=source_tag))

        return self.deduplicate_test_cases(raw_cases, app=app)
