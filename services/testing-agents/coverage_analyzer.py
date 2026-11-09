import hashlib
from typing import Dict, List, Set, Tuple
try:
    from .agent_registry import AgentCapabilities
    from .evidence_collector import EvidenceCollector
    from .schemas import (
        SCHEMA_VERSION,
        ApplicationModel,
        CoverageGap,
        CoverageReport,
        DimensionCoverage,
        Evidence,
        InvalidInputError,
        TestCase,
    )
except ImportError:
    from agent_registry import AgentCapabilities  # type: ignore[no-redef]
    from evidence_collector import EvidenceCollector  # type: ignore[no-redef]
    from schemas import (  # type: ignore[no-redef]
        SCHEMA_VERSION,
        ApplicationModel,
        CoverageGap,
        CoverageReport,
        DimensionCoverage,
        Evidence,
        InvalidInputError,
        TestCase,
    )


class CoverageAnalyzer:
    """
    Identifies covered and uncovered services, dependencies, APIs, and multi-hop workflows
    across an ApplicationModel and produces a schema-validated CoverageReport.
    """

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            agent_id="coverage-analyzer-v1",
            agent_type="coverage_analyzer",
            version="1.0.0",
            deterministic=True,
            can_authorize_execution=False,
            supported_tasks=[
                "service_coverage_analysis",
                "dependency_coverage_analysis",
                "api_coverage_analysis",
                "workflow_coverage_analysis",
                "coverage_gap_identification",
            ],
        )

    @staticmethod
    def _compute_gap_id(application_id: str, dimension: str, target_id: str) -> str:
        raw = f"{application_id}::{dimension}::{target_id}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
        return f"gap-{digest}"

    @staticmethod
    def _fallback_evidence(app: ApplicationModel, dimension: str, target_id: str) -> List[Evidence]:
        return [
            Evidence(
                source=f"application:{app.application_id}",
                type=f"{dimension}_inventory",
                detail=f"Discovered {dimension} '{target_id}' in application model without resilience test coverage.",
            )
        ]

    @staticmethod
    def _discover_workflows(app: ApplicationModel) -> List[Tuple[str, str, List[Evidence]]]:
        """
        Deterministically extracts multi-hop workflows (A -> B -> C) from service dependencies
        and architecture graph edges. Returns list of (workflow_id, workflow_name, evidence).
        """
        service_names = {s.service_id: s.name for s in app.services}
        adj: Dict[str, List[Tuple[str, List[Evidence]]]] = {}

        for dep in sorted(app.dependencies, key=lambda d: (d.source_service_id, d.target_service_id or d.name)):
            if dep.target_service_id and dep.source_service_id != dep.target_service_id:
                adj.setdefault(dep.source_service_id, []).append((dep.target_service_id, list(dep.evidence)))

        if not adj and app.architecture and app.architecture.edges:
            for edge in sorted(app.architecture.edges, key=lambda e: (e.source_node_id, e.target_node_id)):
                if edge.source_node_id != edge.target_node_id:
                    adj.setdefault(edge.source_node_id, []).append((edge.target_node_id, list(edge.evidence)))

        workflows: Dict[str, Tuple[str, List[Evidence]]] = {}
        for src in sorted(adj.keys()):
            for mid, ev1 in adj[src]:
                if mid in adj:
                    for dst, ev2 in adj[mid]:
                        if dst != src:
                            wf_id = f"{src}->{mid}->{dst}"
                            if wf_id not in workflows:
                                n1 = service_names.get(src, src)
                                n2 = service_names.get(mid, mid)
                                n3 = service_names.get(dst, dst)
                                wf_name = f"{n1} -> {n2} -> {n3}"
                                combined_ev = [e for e in (ev1 + ev2) if e.source and e.type and e.detail]
                                workflows[wf_id] = (wf_name, combined_ev)

        return [(wf_id, workflows[wf_id][0], workflows[wf_id][1]) for wf_id in sorted(workflows.keys())]

    def analyze(self, app: ApplicationModel, test_cases: List[TestCase]) -> CoverageReport:
        if app is None or not isinstance(app, ApplicationModel):
            raise InvalidInputError("CoverageAnalyzer.analyze requires a valid ApplicationModel.")
        if test_cases is None or not isinstance(test_cases, list):
            raise InvalidInputError("CoverageAnalyzer.analyze requires a list of TestCase instances.")

        gaps: List[CoverageGap] = []

        # Collect all target identifiers covered by test cases
        direct_targets: Set[str] = set()
        service_targets: Set[str] = set()
        dependency_targets: Set[str] = set()
        api_targets: Set[str] = set()
        workflow_targets: Set[str] = set()

        for tc in test_cases:
            direct_targets.add(tc.target_id)
            if tc.target_type == "service" or tc.test_type in ("availability", "resource_exhaustion", "degradation"):
                service_targets.add(tc.target_id)
            if tc.target_type in ("dependency", "external_dependency") or tc.test_type in (
                "dependency_resilience",
                "failover",
                "latency",
            ):
                dependency_targets.add(tc.target_id)
            if tc.target_type == "api" or tc.test_type == "api_resilience":
                api_targets.add(tc.target_id)
            if tc.target_type == "workflow" or tc.test_type == "workflow_resilience":
                workflow_targets.add(tc.target_id)

        # 1. Service Coverage
        svc_covered: List[str] = []
        svc_uncovered: List[str] = []
        for svc in sorted(app.services, key=lambda s: s.service_id):
            is_cov = (
                svc.service_id in service_targets
                or svc.service_id in direct_targets
                or svc.name in service_targets
            )
            if is_cov:
                svc_covered.append(svc.service_id)
            else:
                svc_uncovered.append(svc.service_id)
                ev = [
                    EvidenceCollector.validate_evidence_item(e)
                    for e in svc.evidence
                    if e.source and e.type and e.detail
                ] or self._fallback_evidence(app, "service", svc.service_id)
                sev = "high" if svc.type in ("database", "message_broker", "gateway", "backend") else "medium"
                gaps.append(
                    CoverageGap(
                        gap_id=self._compute_gap_id(app.application_id, "service", svc.service_id),
                        dimension="service",
                        target_id=svc.service_id,
                        target_name=svc.name,
                        severity=sev,  # type: ignore[arg-type]
                        reason=f"Service '{svc.name}' ({svc.service_id}, type={svc.type}) has no resilience test coverage.",
                        suggested_test_type="availability",
                        evidence=ev,
                    )
                )

        svc_total = len(svc_covered) + len(svc_uncovered)
        service_cov = DimensionCoverage(
            dimension="service",
            total=svc_total,
            covered=len(svc_covered),
            uncovered=len(svc_uncovered),
            coverage_ratio=round(len(svc_covered) / svc_total, 4) if svc_total > 0 else 1.0,
            covered_ids=svc_covered,
            uncovered_ids=svc_uncovered,
        )

        # 2. Dependency Coverage
        dep_covered: List[str] = []
        dep_uncovered: List[str] = []
        seen_dep_ids: Set[str] = set()
        for dep in sorted(app.dependencies, key=lambda d: (d.source_service_id, d.target_service_id or d.name)):
            dep_key = f"{dep.source_service_id}->{dep.target_service_id or dep.name}"
            if dep_key in seen_dep_ids:
                continue
            seen_dep_ids.add(dep_key)

            candidate_keys = {
                dep_key,
                dep.name,
                dep.target_service_id or "",
                f"dep:{dep.source_service_id}:{dep.target_service_id or dep.name}",
            }
            is_cov = bool(candidate_keys & (dependency_targets | direct_targets))
            if is_cov:
                dep_covered.append(dep_key)
            else:
                dep_uncovered.append(dep_key)
                ev = [
                    EvidenceCollector.validate_evidence_item(e)
                    for e in dep.evidence
                    if e.source and e.type and e.detail
                ] or self._fallback_evidence(app, "dependency", dep_key)
                sev = "high" if dep.dependency_type in ("database", "message_queue", "external_api") else "medium"
                gaps.append(
                    CoverageGap(
                        gap_id=self._compute_gap_id(app.application_id, "dependency", dep_key),
                        dimension="dependency",
                        target_id=dep_key,
                        target_name=f"{dep.source_service_id} -> {dep.name} ({dep.dependency_type})",
                        severity=sev,  # type: ignore[arg-type]
                        suggested_test_type="dependency_resilience",
                        reason=f"Dependency '{dep_key}' ({dep.dependency_type}) lacks fault/latency resilience tests.",
                        evidence=ev,
                    )
                )

        dep_total = len(dep_covered) + len(dep_uncovered)
        dependency_cov = DimensionCoverage(
            dimension="dependency",
            total=dep_total,
            covered=len(dep_covered),
            uncovered=len(dep_uncovered),
            coverage_ratio=round(len(dep_covered) / dep_total, 4) if dep_total > 0 else 1.0,
            covered_ids=dep_covered,
            uncovered_ids=dep_uncovered,
        )

        # 3. API Coverage
        api_covered: List[str] = []
        api_uncovered: List[str] = []
        for api in sorted(app.apis, key=lambda a: a.api_id):
            api_keys = {api.api_id, f"{api.method} {api.path}"}
            if api.service_id:
                api_keys.add(api.service_id)
            is_cov = bool(api_keys & api_targets) or (api.api_id in direct_targets)
            if is_cov:
                api_covered.append(api.api_id)
            else:
                api_uncovered.append(api.api_id)
                ev = [
                    EvidenceCollector.validate_evidence_item(e)
                    for e in api.evidence
                    if e.source and e.type and e.detail
                ] or self._fallback_evidence(app, "api", api.api_id)
                sev = "high" if api.auth_required is False else "medium"
                gaps.append(
                    CoverageGap(
                        gap_id=self._compute_gap_id(app.application_id, "api", api.api_id),
                        dimension="api",
                        target_id=api.api_id,
                        target_name=f"{api.method} {api.path}",
                        severity=sev,  # type: ignore[arg-type]
                        reason=f"API endpoint '{api.method} {api.path}' ({api.api_id}) has no API resilience test coverage.",
                        suggested_test_type="api_resilience",
                        evidence=ev,
                    )
                )

        api_total = len(api_covered) + len(api_uncovered)
        api_cov = DimensionCoverage(
            dimension="api",
            total=api_total,
            covered=len(api_covered),
            uncovered=len(api_uncovered),
            coverage_ratio=round(len(api_covered) / api_total, 4) if api_total > 0 else 1.0,
            covered_ids=api_covered,
            uncovered_ids=api_uncovered,
        )

        # 4. Workflow Coverage
        workflows = self._discover_workflows(app)
        wf_covered: List[str] = []
        wf_uncovered: List[str] = []
        for wf_id, wf_name, wf_ev in workflows:
            hops = wf_id.split("->")
            hop_edges = {f"{hops[i]}->{hops[i + 1]}" for i in range(len(hops) - 1)}
            is_cov = (
                wf_id in workflow_targets
                or wf_id in direct_targets
                or (hop_edges and hop_edges.issubset(set(dep_covered)))
            )
            if is_cov:
                wf_covered.append(wf_id)
            else:
                wf_uncovered.append(wf_id)
                ev = [
                    EvidenceCollector.validate_evidence_item(e)
                    for e in wf_ev
                    if e.source and e.type and e.detail
                ] or self._fallback_evidence(app, "workflow", wf_id)
                gaps.append(
                    CoverageGap(
                        gap_id=self._compute_gap_id(app.application_id, "workflow", wf_id),
                        dimension="workflow",
                        target_id=wf_id,
                        target_name=wf_name,
                        severity="high",
                        reason=f"Multi-service workflow '{wf_name}' ({wf_id}) lacks end-to-end workflow resilience coverage.",
                        suggested_test_type="workflow_resilience",
                        evidence=ev,
                    )
                )

        wf_total = len(wf_covered) + len(wf_uncovered)
        workflow_cov = DimensionCoverage(
            dimension="workflow",
            total=wf_total,
            covered=len(wf_covered),
            uncovered=len(wf_uncovered),
            coverage_ratio=round(len(wf_covered) / wf_total, 4) if wf_total > 0 else 1.0,
            covered_ids=wf_covered,
            uncovered_ids=wf_uncovered,
        )

        total_entities = svc_total + dep_total + api_total + wf_total
        covered_entities = len(svc_covered) + len(dep_covered) + len(api_covered) + len(wf_covered)
        uncovered_entities = len(svc_uncovered) + len(dep_uncovered) + len(api_uncovered) + len(wf_uncovered)
        overall_ratio = round(covered_entities / total_entities, 4) if total_entities > 0 else 1.0

        return CoverageReport(
            application_id=app.application_id,
            schema_version=SCHEMA_VERSION,
            total_entities=total_entities,
            covered_entities=covered_entities,
            uncovered_entities=uncovered_entities,
            overall_coverage_ratio=overall_ratio,
            service_coverage=service_cov,
            dependency_coverage=dependency_cov,
            api_coverage=api_cov,
            workflow_coverage=workflow_cov,
            gaps=sorted(gaps, key=lambda g: g.gap_id),
        )
