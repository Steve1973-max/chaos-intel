import asyncio
import pytest
from agent_registry import (
    AgentCapabilities,
    AgentRegistry,
    DeterministicBaselineProvider,
    IntelligenceProvider,
    TestSuggestion,
)
from coverage_analyzer import CoverageAnalyzer
from evidence_collector import EvidenceCollector
from test_case_generator import TestCaseGenerator
from test_planner import TestPlanner
from test_prioritizer import TestPrioritizer
from schemas import (
    Api,
    ApplicationModel,
    ArchitectureGraph,
    Dependency,
    Evidence,
    EvidenceTraceabilityError,
    ExperimentSpecification,
    Fault,
    BlastRadius,
    SteadyState,
    Rollback,
    Safety,
    Target,
    GraphEdge,
    GraphNode,
    InvalidInputError,
    PriorityBreakdown,
    RiskFinding,
    SafetyViolationError,
    SchemaValidationError,
    SchemaValidator,
    Service,
    Technology,
    TestCandidate,
    TestCase,
    TestStep,
)


@pytest.fixture
def sample_app() -> ApplicationModel:
    ev_compose = Evidence(source="docker-compose.yml", type="config", detail="service definition")
    ev_openapi = Evidence(source="openapi.yaml", type="spec", detail="endpoint definition")
    ev_pkg = Evidence(source="package.json", type="manifest", detail="dependency declaration")

    services = [
        Service(
            service_id="svc-gateway",
            application_id="app-100",
            name="API Gateway",
            type="gateway",
            technology="FastAPI",
            source_path="services/gateway",
            ports=[8000],
            confidence=0.95,
            evidence=[ev_compose],
        ),
        Service(
            service_id="svc-orders",
            application_id="app-100",
            name="Order Service",
            type="backend",
            technology="FastAPI",
            source_path="services/orders",
            ports=[8001],
            confidence=0.92,
            evidence=[ev_compose],
        ),
        Service(
            service_id="svc-db",
            application_id="app-100",
            name="Orders Database",
            type="database",
            technology="PostgreSQL",
            source_path="infra/db",
            ports=[5432],
            confidence=0.98,
            evidence=[ev_compose],
        ),
        Service(
            service_id="svc-analytics",
            application_id="app-100",
            name="Analytics Worker",
            type="worker",
            technology="Python",
            source_path="services/analytics",
            ports=[],
            confidence=0.85,
            evidence=[ev_pkg],
        ),
    ]

    dependencies = [
        Dependency(
            source_service_id="svc-gateway",
            target_service_id="svc-orders",
            dependency_type="http",
            name="svc-orders",
            confidence=0.90,
            evidence=[ev_compose],
        ),
        Dependency(
            source_service_id="svc-orders",
            target_service_id="svc-db",
            dependency_type="database",
            name="postgres",
            confidence=0.96,
            evidence=[ev_compose],
        ),
    ]

    apis = [
        Api(
            api_id="api-create-order",
            service_id="svc-gateway",
            method="POST",
            path="/orders",
            auth_required=False,
            confidence=0.91,
            evidence=[ev_openapi],
        ),
        Api(
            api_id="api-health",
            service_id="svc-gateway",
            method="GET",
            path="/health",
            auth_required=True,
            confidence=0.95,
            evidence=[ev_openapi],
        ),
    ]

    architecture = ArchitectureGraph(
        nodes=[
            GraphNode(
                node_id="svc-gateway",
                node_type="service",
                name="API Gateway",
                service_id="svc-gateway",
                confidence=0.95,
                evidence=[ev_compose],
            ),
            GraphNode(
                node_id="svc-orders",
                node_type="service",
                name="Order Service",
                service_id="svc-orders",
                confidence=0.92,
                evidence=[ev_compose],
            ),
            GraphNode(
                node_id="svc-db",
                node_type="database",
                name="Orders Database",
                service_id="svc-db",
                confidence=0.98,
                evidence=[ev_compose],
            ),
        ],
        edges=[
            GraphEdge(
                edge_id="edge-gw-orders",
                source_node_id="svc-gateway",
                target_node_id="svc-orders",
                edge_type="http",
                protocol="http",
                confidence=0.90,
                evidence=[ev_compose],
            ),
            GraphEdge(
                edge_id="edge-orders-db",
                source_node_id="svc-orders",
                target_node_id="svc-db",
                edge_type="database",
                protocol="tcp",
                confidence=0.96,
                evidence=[ev_compose],
            ),
        ],
    )

    risks = [
        RiskFinding(
            risk_id="risk-spof-db",
            application_id="app-100",
            category="availability",
            risk_type="single_point_of_failure",
            severity="critical",
            title="Database SPOF on Orders Database",
            description="Orders Database is a critical single point of failure.",
            target_type="service",
            target_id="svc-db",
            confidence=0.96,
            evidence=[ev_compose],
        ),
        RiskFinding(
            risk_id="risk-unauth-api",
            application_id="app-100",
            category="api",
            risk_type="unauthenticated_api",
            severity="medium",
            title="Unauthenticated POST /orders endpoint",
            description="Endpoint lacks authentication.",
            target_type="api",
            target_id="api-create-order",
            confidence=0.88,
            evidence=[ev_openapi],
        ),
    ]

    candidates = [
        TestCandidate(
            candidate_id="cand-db-avail",
            application_id="app-100",
            target_type="service",
            target_id="svc-db",
            test_type="availability",
            title="Database Availability Outage Test",
            hypothesis="Order Service handles database unavailability with bounded retries and circuit breaking.",
            reason="Critical SPOF database identified.",
            expected_failure_mode="Unhandled connection errors and cascading 500 responses.",
            priority="critical",
            confidence=0.96,
            prerequisites=["Staging environment isolated"],
            evidence=[ev_compose],
            related_risk_ids=["risk-spof-db"],
            required_capabilities=["container_pause", "log_collection"],
            suggested_observations=["HTTP 503 error rate", "DB connection pool metrics"],
        ),
        TestCandidate(
            candidate_id="cand-api-res",
            application_id="app-100",
            target_type="api",
            target_id="api-create-order",
            test_type="api_resilience",
            title="POST /orders API Resilience Test",
            hypothesis="API Gateway rate-limits and degrades gracefully under malformed/burst load.",
            reason="Public unauthenticated write endpoint.",
            expected_failure_mode="Resource saturation on gateway.",
            priority="medium",
            confidence=0.82,
            prerequisites=["Rate limiter metrics enabled"],
            evidence=[ev_openapi],
            related_risk_ids=["risk-unauth-api"],
            required_capabilities=["http_load_generation"],
            suggested_observations=["Gateway p99 latency", "429 response count"],
        ),
    ]

    experiments = [
        ExperimentSpecification(
            experiment_id="exp-db-001",
            application_id="app-100",
            candidate_ids=["cand-db-avail"],
            name="DB Outage Spec",
            hypothesis="Order Service handles database unavailability.",
            status="draft",
            target=Target(type="service", id="svc-db", name="Orders Database"),
            fault=Fault(type="availability", method="container_pause", parameters={"duration": 30}),
            duration_seconds=30,
            blast_radius=BlastRadius(scope="single_service", max_affected_components=1),
            steady_state=SteadyState(required=True, checks=["db_ping_ok"]),
            observations=["HTTP 503 error rate"],
            abort_conditions=[],
            rollback=Rollback(strategy="unpause_container", automatic=True, verification_required=True),
            prerequisites=["Staging environment isolated"],
            safety=Safety(requires_approval=True, rollback_required=True, production_allowed=False),
            confidence=0.96,
            evidence=[ev_compose],
        )
    ]

    return ApplicationModel(
        application_id="app-100",
        name="OrderProcessingApp",
        technologies=[
            Technology(name="FastAPI", category="framework", confidence=0.95, evidence=[ev_pkg]),
            Technology(name="PostgreSQL", category="database", confidence=0.98, evidence=[ev_compose]),
        ],
        services=services,
        dependencies=dependencies,
        apis=apis,
        architecture=architecture,
        risks=risks,
        test_candidates=candidates,
        experiments=experiments,
    )


# ---------------------------------------------------------------------------
# 1. Test Planning & Schema Validation
# ---------------------------------------------------------------------------

def test_planner_end_to_end_creates_valid_test_plan(sample_app: ApplicationModel):
    planner = TestPlanner()
    plan = planner.create_test_plan(sample_app)

    assert plan.application_id == "app-100"
    assert plan.application_name == "OrderProcessingApp"
    assert plan.execution_authorized is False
    assert plan.safety_gate_status == "pending_safety_engine"
    assert plan.schema_version == "1.0.0"
    assert len(plan.test_cases) == 3  # 2 explicit candidates + 1 multi-hop workflow suggestion
    assert plan.summary.total_test_cases == 3
    assert plan.summary.total_risks_addressed == 2

    # Explicitly validate against shared JSON Schemas
    validator = SchemaValidator()
    validator.validate_test_plan(plan)
    for tc in plan.test_cases:
        validator.validate_test_case(tc)
        assert tc.execution_authorized is False
        assert tc.requires_safety_decision is True
        assert tc.mode == "plan_only"


def test_planner_auto_derives_candidates_when_none_present(sample_app: ApplicationModel):
    app_no_candidates = sample_app.model_copy(deep=True)
    app_no_candidates.test_candidates = []
    app_no_candidates.risks = []

    planner = TestPlanner()
    plan = planner.create_test_plan(app_no_candidates, auto_derive_candidates=True)

    assert len(plan.test_cases) > 0
    assert plan.execution_authorized is False
    SchemaValidator().validate_test_plan(plan)


def test_planner_async_interface(sample_app: ApplicationModel):
    planner = TestPlanner()
    sync_plan = planner.create_test_plan(sample_app)
    async_plan = asyncio.run(planner.create_test_plan_async(sample_app))

    assert sync_plan.model_dump() == async_plan.model_dump()


# ---------------------------------------------------------------------------
# 2. Test Case Generation & Duplicate Detection
# ---------------------------------------------------------------------------

def test_generator_creates_structured_test_case_and_links_experiments(sample_app: ApplicationModel):
    generator = TestCaseGenerator()
    tc = generator.from_candidate(sample_app.test_candidates[0], app=sample_app)

    assert tc.test_case_id.startswith("tc-")
    assert tc.target_name == "Orders Database"
    assert tc.related_experiment_ids == ["exp-db-001"]
    assert tc.related_risk_ids == ["risk-spof-db"]
    assert len(tc.test_steps) == 4
    assert [s.phase for s in tc.test_steps] == [
        "steady_state_check",
        "stimulus_plan",
        "observation",
        "recovery_verification",
    ]
    assert len(tc.assertions) >= 3
    assert tc.execution_authorized is False


def test_generator_deduplicates_and_merges_duplicate_candidates(sample_app: ApplicationModel):
    generator = TestCaseGenerator()
    cand1 = sample_app.test_candidates[0].model_copy(deep=True)
    cand2 = sample_app.test_candidates[0].model_copy(deep=True)
    cand2.candidate_id = "cand-db-avail-duplicate"
    cand2.priority = "high"
    cand2.confidence = 0.99
    cand2.evidence = [Evidence(source="k8s/db.yaml", type="manifest", detail="replicas: 1")]
    cand2.related_risk_ids = ["risk-extra-db"]
    cand2.prerequisites = ["Extra DB backup snapshot verified"]

    cases, removed_count = generator.generate(
        [cand1, cand2], app=sample_app, include_provider_suggestions=False
    )

    assert removed_count == 1
    assert len(cases) == 1
    merged = cases[0]
    assert merged.confidence == 0.99
    assert "cand-db-avail" in merged.metadata["merged_candidate_ids"]
    assert "cand-db-avail-duplicate" in merged.metadata["merged_candidate_ids"]
    assert set(merged.related_risk_ids) == {"risk-spof-db", "risk-extra-db"}
    assert any(e.source == "k8s/db.yaml" for e in merged.evidence)
    assert any(e.source == "docker-compose.yml" for e in merged.evidence)


# ---------------------------------------------------------------------------
# 3. Prioritization & Explainability
# ---------------------------------------------------------------------------

def test_prioritizer_ranks_critical_spof_above_medium_api(sample_app: ApplicationModel):
    generator = TestCaseGenerator()
    prioritizer = TestPrioritizer()

    raw_cases, _ = generator.generate(
        sample_app.test_candidates, app=sample_app, include_provider_suggestions=False
    )
    ranked = prioritizer.prioritize(raw_cases, app=sample_app)

    assert len(ranked) == 2
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2
    # Critical database SPOF must rank above medium unauthenticated API
    assert ranked[0].target_id == "svc-db"
    assert ranked[0].priority_score > ranked[1].priority_score
    assert ranked[0].priority_breakdown.severity_score > ranked[1].priority_breakdown.severity_score
    assert ranked[0].priority_breakdown.dependency_criticality_score > ranked[1].priority_breakdown.dependency_criticality_score
    assert "ranked" in ranked[0].priority_breakdown.explanation.lower()
    assert len(ranked[0].priority_breakdown.factors) >= 3


# ---------------------------------------------------------------------------
# 4. Coverage Analysis & Coverage Gaps
# ---------------------------------------------------------------------------

def test_coverage_analyzer_identifies_uncovered_services_dependencies_apis_workflows(sample_app: ApplicationModel):
    generator = TestCaseGenerator()
    analyzer = CoverageAnalyzer()

    # Generate only from explicit candidates (no workflow suggestion)
    cases, _ = generator.generate(
        sample_app.test_candidates, app=sample_app, include_provider_suggestions=False
    )
    report = analyzer.analyze(sample_app, cases)

    # Services: 4 total (svc-db covered; svc-gateway, svc-orders, svc-analytics uncovered)
    assert report.service_coverage.total == 4
    assert report.service_coverage.covered == 1
    assert "svc-db" in report.service_coverage.covered_ids
    assert "svc-analytics" in report.service_coverage.uncovered_ids

    # APIs: 2 total (api-create-order covered; api-health uncovered)
    assert report.api_coverage.total == 2
    assert report.api_coverage.covered == 1
    assert report.api_coverage.uncovered_ids == ["api-health"]

    # Workflows: 1 multi-hop workflow svc-gateway->svc-orders->svc-db uncovered when suggestions disabled
    assert report.workflow_coverage.total == 1
    assert report.workflow_coverage.uncovered == 1
    assert "svc-gateway->svc-orders->svc-db" in report.workflow_coverage.uncovered_ids

    # Every gap must have traceable evidence and a suggested test type
    assert len(report.gaps) == report.uncovered_entities
    for gap in report.gaps:
        assert len(gap.evidence) >= 1
        assert gap.gap_id.startswith("gap-")

    SchemaValidator().validate_coverage_report(report)


# ---------------------------------------------------------------------------
# 5. Evidence Traceability
# ---------------------------------------------------------------------------

def test_evidence_collector_rejects_candidate_without_evidence(sample_app: ApplicationModel):
    collector = EvidenceCollector()
    bad_candidate = TestCandidate(
        candidate_id="cand-no-ev",
        application_id="app-100",
        target_type="service",
        target_id="svc-nonexistent",
        test_type="availability",
        title="Test without evidence",
        hypothesis="Should fail traceability check",
        reason="Missing evidence",
        expected_failure_mode="Unknown",
        priority="low",
        confidence=0.5,
        prerequisites=[],
        evidence=[],
    )

    with pytest.raises(EvidenceTraceabilityError, match="no traceable evidence"):
        collector.collect_for_candidate(bad_candidate, app=sample_app)


def test_evidence_collector_rejects_blank_evidence_fields():
    collector = EvidenceCollector()
    with pytest.raises(EvidenceTraceabilityError):
        collector.validate_evidence_item(Evidence(source="  ", type="config", detail="valid"))


# ---------------------------------------------------------------------------
# 6. Invalid Inputs & Safety Guardrails
# ---------------------------------------------------------------------------

def test_invalid_inputs_rejected_cleanly(sample_app: ApplicationModel):
    planner = TestPlanner()
    generator = TestCaseGenerator()
    prioritizer = TestPrioritizer()
    analyzer = CoverageAnalyzer()

    with pytest.raises(InvalidInputError):
        planner.create_test_plan(None)  # type: ignore[arg-type]

    empty_id_app = sample_app.model_copy(deep=True)
    empty_id_app.application_id = "   "
    with pytest.raises(InvalidInputError, match="application_id"):
        planner.create_test_plan(empty_id_app)

    with pytest.raises(InvalidInputError):
        generator.from_candidate(None)  # type: ignore[arg-type]

    with pytest.raises(InvalidInputError):
        prioritizer.prioritize("not-a-list")  # type: ignore[arg-type]

    with pytest.raises(InvalidInputError):
        analyzer.analyze(sample_app, None)  # type: ignore[arg-type]


def test_ai_provider_and_agent_cannot_authorize_execution(sample_app: ApplicationModel):
    with pytest.raises(SafetyViolationError):
        AgentCapabilities(
            agent_id="rogue-agent",
            agent_type="test_planner",
            can_authorize_execution=True,
        )

    with pytest.raises(SafetyViolationError):
        TestSuggestion(
            target_type="service",
            target_id="svc-db",
            test_type="availability",
            title="Rogue suggestion",
            hypothesis="Hypothesis",
            reason="Reason",
            expected_failure_mode="Failure",
            evidence=[Evidence(source="docker-compose.yml", type="config", detail="db")],
            execution_authorized=True,
        )

    with pytest.raises(EvidenceTraceabilityError):
        TestSuggestion(
            target_type="service",
            target_id="svc-db",
            test_type="availability",
            title="Unbacked suggestion",
            hypothesis="Hypothesis",
            reason="Reason",
            expected_failure_mode="Failure",
            evidence=[],
        )


def test_custom_model_agnostic_provider_integration(sample_app: ApplicationModel):
    class CustomMockLLMProvider:
        @property
        def provider_id(self) -> str:
            return "mock-llm-provider-v1"

        @property
        def is_deterministic(self) -> bool:
            return False

        def suggest_test_cases(self, app: ApplicationModel):
            return [
                TestSuggestion(
                    target_type="service",
                    target_id="svc-analytics",
                    test_type="resource_exhaustion",
                    title="Analytics Worker Memory Pressure Test",
                    hypothesis="Worker handles memory pressure without losing queued jobs.",
                    reason="LLM identified worker batch processing pattern.",
                    expected_failure_mode="OOMKill of worker container.",
                    priority="medium",
                    confidence=0.78,
                    evidence=[Evidence(source="package.json", type="manifest", detail="worker dependency")],
                )
            ]

        def explain_priority(self, title: str, breakdown: PriorityBreakdown) -> str:
            return f"LLM-enriched explanation for {title}: score={breakdown.total_score}"

    planner = TestPlanner(provider=CustomMockLLMProvider())
    plan = planner.create_test_plan(sample_app)

    assert plan.provider_id == "mock-llm-provider-v1"
    assert plan.execution_authorized is False
    analytics_cases = [tc for tc in plan.test_cases if tc.target_id == "svc-analytics"]
    assert len(analytics_cases) == 1
    assert analytics_cases[0].generation_source == "ai_suggestion"
    assert analytics_cases[0].execution_authorized is False


# ---------------------------------------------------------------------------
# 7. Deterministic Output Consistency
# ---------------------------------------------------------------------------

def test_deterministic_output_consistency_across_runs_and_input_order(sample_app: ApplicationModel):
    planner = TestPlanner()
    plan1 = planner.create_test_plan(sample_app)
    plan2 = planner.create_test_plan(sample_app)

    assert plan1.plan_id == plan2.plan_id
    assert plan1.model_dump() == plan2.model_dump()

    # Reverse the order of candidates, services, risks, and APIs and verify identical output
    shuffled_app = sample_app.model_copy(deep=True)
    shuffled_app.test_candidates = list(reversed(shuffled_app.test_candidates))
    shuffled_app.services = list(reversed(shuffled_app.services))
    shuffled_app.risks = list(reversed(shuffled_app.risks))
    shuffled_app.apis = list(reversed(shuffled_app.apis))

    plan3 = planner.create_test_plan(shuffled_app)
    assert plan1.plan_id == plan3.plan_id
    assert plan1.model_dump() == plan3.model_dump()

