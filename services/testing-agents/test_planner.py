import hashlib
from typing import Dict, List, Optional
try:
    from .agent_registry import (
        AgentCapabilities,
        AgentRegistry,
        DeterministicBaselineProvider,
        IntelligenceProvider,
    )
    from .coverage_analyzer import CoverageAnalyzer
    from .evidence_collector import EvidenceCollector
    from .test_case_generator import TestCaseGenerator
    from .test_prioritizer import TestPrioritizer
    from .schemas import (
        SCHEMA_VERSION,
        ApplicationModel,
        InvalidInputError,
        SchemaValidator,
        TestCandidate,
        TestCase,
        TestPlan,
        TestPlanSummary,
    )
except ImportError:
    from agent_registry import (  # type: ignore[no-redef]
        AgentCapabilities,
        AgentRegistry,
        DeterministicBaselineProvider,
        IntelligenceProvider,
    )
    from coverage_analyzer import CoverageAnalyzer  # type: ignore[no-redef]
    from evidence_collector import EvidenceCollector  # type: ignore[no-redef]
    from test_case_generator import TestCaseGenerator  # type: ignore[no-redef]
    from test_prioritizer import TestPrioritizer  # type: ignore[no-redef]
    from schemas import (  # type: ignore[no-redef]
        SCHEMA_VERSION,
        ApplicationModel,
        InvalidInputError,
        SchemaValidator,
        TestCandidate,
        TestCase,
        TestPlan,
        TestPlanSummary,
    )

# Reuse Application Intelligence candidate and risk engines when needed without duplicating logic
from src.strategy.engine import generate_test_candidates
from src.risk.engine import analyze_risks


class TestPlanner:
    """
    Coordinates the Testing Agents pipeline to convert Application Intelligence outputs
    (ApplicationModel, ArchitectureGraph, RiskFindings, TestCandidates, ExperimentSpecifications)
    into a structured, explainable, and schema-validated TestPlan.

    Safety invariants:
    - No direct database access.
    - No direct execution of chaos experiments.
    - No bypassing the Safety & Policy Engine (execution_authorized is always False).
    """

    __test__ = False

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        provider: Optional[IntelligenceProvider] = None,
        schema_validator: Optional[SchemaValidator] = None,
    ) -> None:
        self.provider: IntelligenceProvider = provider or DeterministicBaselineProvider()
        self.evidence_collector = EvidenceCollector()
        self.prioritizer = TestPrioritizer(provider=self.provider)
        self.generator = TestCaseGenerator(
            evidence_collector=self.evidence_collector,
            prioritizer=self.prioritizer,
            provider=self.provider,
        )
        self.coverage_analyzer = CoverageAnalyzer()
        self.schema_validator = schema_validator or SchemaValidator()

        self.registry = registry or AgentRegistry()
        self.registry.register_provider(self.provider, overwrite=True)
        for agent in (
            self,
            self.evidence_collector,
            self.generator,
            self.prioritizer,
            self.coverage_analyzer,
        ):
            self.registry.register_agent(agent, overwrite=True)

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            agent_id="test-planner-v1",
            agent_type="test_planner",
            version="1.0.0",
            deterministic=self.provider.is_deterministic,
            can_authorize_execution=False,
            supported_tasks=[
                "test_plan_generation",
                "candidate_orchestration",
                "coverage_gap_integration",
                "schema_contract_validation",
            ],
        )

    @staticmethod
    def _validate_application_input(app: ApplicationModel) -> None:
        if app is None or not isinstance(app, ApplicationModel):
            raise InvalidInputError("TestPlanner requires a valid ApplicationModel instance.")
        if not app.application_id or not str(app.application_id).strip():
            raise InvalidInputError("ApplicationModel.application_id must be a non-empty string.")
        if not app.name or not str(app.name).strip():
            raise InvalidInputError("ApplicationModel.name must be a non-empty string.")

    @staticmethod
    def compute_plan_id(application_id: str, test_cases: List[TestCase]) -> str:
        tc_ids = ",".join(tc.test_case_id for tc in test_cases)
        canonical = f"{application_id.strip()}::{SCHEMA_VERSION}::{tc_ids}"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        return f"plan-{digest}"

    def _resolve_candidates(
        self, app: ApplicationModel, auto_derive_from_architecture: bool
    ) -> List[TestCandidate]:
        working_app = app.model_copy(deep=True)
        if not working_app.risks and auto_derive_from_architecture:
            risk_res = analyze_risks(working_app)
            working_app.risks = risk_res.findings if hasattr(risk_res, "findings") else list(risk_res)
        if working_app.test_candidates:
            return list(working_app.test_candidates)
        if auto_derive_from_architecture:
            return generate_test_candidates(working_app)
        return []

    def create_test_plan(
        self,
        app: ApplicationModel,
        auto_derive_candidates: bool = True,
        include_provider_suggestions: bool = True,
        validate_schemas: bool = True,
    ) -> TestPlan:
        """
        Synchronously generates a deterministic, explainable, and schema-validated TestPlan.
        """
        self._validate_application_input(app)

        working_app = app.model_copy(deep=True)
        if not working_app.risks and auto_derive_candidates:
            risk_res = analyze_risks(working_app)
            working_app.risks = risk_res.findings if hasattr(risk_res, "findings") else list(risk_res)

        candidates = self._resolve_candidates(working_app, auto_derive_from_architecture=auto_derive_candidates)

        # Generate and deduplicate test cases
        generated_cases, deduplicated_count = self.generator.generate(
            candidates=candidates,
            app=working_app,
            include_provider_suggestions=include_provider_suggestions,
        )

        # Rank and prioritize test cases
        ranked_cases = self.prioritizer.prioritize(generated_cases, app=working_app)

        # Analyze coverage and gaps
        coverage_report = self.coverage_analyzer.analyze(working_app, ranked_cases)

        # Aggregate plan-level evidence
        plan_evidence = self.evidence_collector.collect_plan_evidence(
            working_app, [tc.evidence for tc in ranked_cases]
        )

        # Compute summary statistics
        by_priority: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        by_test_type: Dict[str, int] = {}
        addressed_risk_ids = set()

        for tc in ranked_cases:
            by_priority[tc.priority] = by_priority.get(tc.priority, 0) + 1
            by_test_type[tc.test_type] = by_test_type.get(tc.test_type, 0) + 1
            for rid in tc.related_risk_ids:
                addressed_risk_ids.add(rid)

        if ranked_cases:
            plan_confidence = round(sum(tc.confidence for tc in ranked_cases) / len(ranked_cases), 4)
            plan_status = (
                "requires_review"
                if any(tc.status == "requires_review" for tc in ranked_cases)
                else "draft"
            )
        else:
            plan_confidence = 0.0
            plan_status = "draft"

        summary = TestPlanSummary(
            total_test_cases=len(ranked_cases),
            by_priority=by_priority,
            by_test_type=dict(sorted(by_test_type.items())),
            deduplicated_count=deduplicated_count,
            total_risks_addressed=len(addressed_risk_ids),
            total_coverage_gaps=len(coverage_report.gaps),
            overall_coverage_ratio=coverage_report.overall_coverage_ratio,
        )

        plan_id = self.compute_plan_id(working_app.application_id, ranked_cases)
        plan = TestPlan(
            plan_id=plan_id,
            schema_version=SCHEMA_VERSION,
            application_id=working_app.application_id,
            application_name=working_app.name,
            status=plan_status,  # type: ignore[arg-type]
            execution_authorized=False,
            safety_gate_status="pending_safety_engine",
            provider_id=self.provider.provider_id,
            confidence=plan_confidence,
            summary=summary,
            test_cases=ranked_cases,
            coverage_report=coverage_report,
            evidence=plan_evidence,
            metadata={
                "analysis_version": working_app.analysis_version,
                "deterministic": self.provider.is_deterministic,
                "registered_agents": [a.agent_id for a in self.registry.list_agents()],
            },
        )

        if validate_schemas:
            for tc in plan.test_cases:
                self.schema_validator.validate_test_case(tc)
            self.schema_validator.validate_coverage_report(plan.coverage_report)
            self.schema_validator.validate_test_plan(plan)

        return plan

    async def create_test_plan_async(
        self,
        app: ApplicationModel,
        auto_derive_candidates: bool = True,
        include_provider_suggestions: bool = True,
        validate_schemas: bool = True,
    ) -> TestPlan:
        """
        Asynchronous entrypoint supporting non-blocking worker and future LLM provider integration.
        """
        return self.create_test_plan(
            app=app,
            auto_derive_candidates=auto_derive_candidates,
            include_provider_suggestions=include_provider_suggestions,
            validate_schemas=validate_schemas,
        )
