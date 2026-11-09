from typing import List, Optional, Tuple
try:
    from .agent_registry import AgentCapabilities
    from .schemas import (
        ApplicationModel,
        Evidence,
        EvidenceTraceabilityError,
        InvalidInputError,
        RiskFinding,
        TestCandidate,
    )
except ImportError:
    from agent_registry import AgentCapabilities  # type: ignore[no-redef]
    from schemas import (  # type: ignore[no-redef]
        ApplicationModel,
        Evidence,
        EvidenceTraceabilityError,
        InvalidInputError,
        RiskFinding,
        TestCandidate,
    )


class EvidenceCollector:
    """
    Collects, normalizes, deduplicates, and validates source evidence and reasoning
    for generated test cases and test plans.
    """

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            agent_id="evidence-collector-v1",
            agent_type="evidence_collector",
            version="1.0.0",
            deterministic=True,
            can_authorize_execution=False,
            supported_tasks=["evidence_collection", "evidence_deduplication", "traceability_validation"],
        )

    @staticmethod
    def validate_evidence_item(item: Evidence) -> Evidence:
        if not isinstance(item, Evidence):
            if isinstance(item, dict):
                try:
                    item = Evidence(**item)
                except Exception as exc:
                    raise EvidenceTraceabilityError(f"Malformed evidence dictionary: {exc}") from exc
            else:
                raise EvidenceTraceabilityError(f"Invalid evidence object type: {type(item).__name__}")

        source = (item.source or "").strip()
        ev_type = (item.type or "").strip()
        detail = (item.detail or "").strip()
        if not source or not ev_type or not detail:
            raise EvidenceTraceabilityError(
                "Every Evidence item must contain non-empty 'source', 'type', and 'detail' fields."
            )
        return Evidence(source=source, type=ev_type, detail=detail)

    @classmethod
    def deduplicate_evidence(cls, evidence_items: List[Evidence]) -> List[Evidence]:
        seen = set()
        deduped: List[Evidence] = []
        for raw_item in evidence_items:
            item = cls.validate_evidence_item(raw_item)
            key = (item.source, item.type, item.detail)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return sorted(deduped, key=lambda e: (e.source, e.type, e.detail))

    def collect_for_candidate(
        self,
        candidate: TestCandidate,
        app: Optional[ApplicationModel] = None,
    ) -> Tuple[List[Evidence], str]:
        """
        Collects all traceable evidence for a TestCandidate from:
        1. The candidate's own evidence list.
        2. Linked RiskFindings in ApplicationModel (via related_risk_ids or matching target).
        3. Target architectural components (Service, Dependency, Api, GraphNode, GraphEdge).
        Returns (deduplicated_evidence, explainable_reasoning).
        """
        if candidate is None or not isinstance(candidate, TestCandidate):
            raise InvalidInputError("collect_for_candidate requires a valid TestCandidate instance.")

        collected: List[Evidence] = []
        reasoning_parts: List[str] = []

        # 1. Direct candidate evidence
        if candidate.evidence:
            for ev in candidate.evidence:
                collected.append(self.validate_evidence_item(ev))
            reasoning_parts.append(
                f"Direct candidate evidence ({len(candidate.evidence)} item(s)) from {candidate.candidate_id}"
            )

        if app is not None:
            if not isinstance(app, ApplicationModel):
                raise InvalidInputError("app must be a valid ApplicationModel instance when provided.")

            # 2. Evidence from related RiskFindings
            related_risks: List[RiskFinding] = []
            risk_id_set = set(candidate.related_risk_ids or [])
            for risk in app.risks:
                if risk.risk_id in risk_id_set or (
                    risk.target_type == candidate.target_type and risk.target_id == candidate.target_id
                ):
                    related_risks.append(risk)

            for risk in sorted(related_risks, key=lambda r: r.risk_id):
                for ev in risk.evidence:
                    if ev.source and ev.type and ev.detail:
                        collected.append(self.validate_evidence_item(ev))
                reasoning_parts.append(
                    f"Corroborated by risk '{risk.risk_id}' ({risk.risk_type}, severity={risk.severity})"
                )

            # 3. Evidence from target component in ApplicationModel
            target_ev_count = 0
            if candidate.target_type == "service":
                for svc in app.services:
                    if svc.service_id == candidate.target_id or svc.name == candidate.target_id:
                        for ev in svc.evidence:
                            if ev.source and ev.type and ev.detail:
                                collected.append(self.validate_evidence_item(ev))
                                target_ev_count += 1
            elif candidate.target_type in ("dependency", "external_dependency"):
                for dep in app.dependencies:
                    dep_ids = {
                        dep.name,
                        dep.target_service_id,
                        f"{dep.source_service_id}->{dep.target_service_id or dep.name}",
                    }
                    if candidate.target_id in dep_ids:
                        for ev in dep.evidence:
                            if ev.source and ev.type and ev.detail:
                                collected.append(self.validate_evidence_item(ev))
                                target_ev_count += 1
            elif candidate.target_type == "api":
                for api in app.apis:
                    if api.api_id == candidate.target_id or f"{api.method} {api.path}" == candidate.target_id:
                        for ev in api.evidence:
                            if ev.source and ev.type and ev.detail:
                                collected.append(self.validate_evidence_item(ev))
                                target_ev_count += 1

            # Also check architecture graph nodes/edges matching target_id
            if app.architecture:
                for node in app.architecture.nodes:
                    if node.node_id == candidate.target_id or node.service_id == candidate.target_id:
                        for ev in node.evidence:
                            if ev.source and ev.type and ev.detail:
                                collected.append(self.validate_evidence_item(ev))
                                target_ev_count += 1
                for edge in app.architecture.edges:
                    if edge.edge_id == candidate.target_id:
                        for ev in edge.evidence:
                            if ev.source and ev.type and ev.detail:
                                collected.append(self.validate_evidence_item(ev))
                                target_ev_count += 1

            if target_ev_count > 0:
                reasoning_parts.append(
                    f"Backed by {target_ev_count} architectural component evidence record(s) for '{candidate.target_id}'"
                )

        deduped = self.deduplicate_evidence(collected)
        if not deduped:
            raise EvidenceTraceabilityError(
                f"Test candidate '{candidate.candidate_id}' targeting '{candidate.target_id}' has no traceable evidence."
            )

        if candidate.reason and candidate.reason.strip():
            reasoning_parts.insert(0, candidate.reason.strip())

        sources_summary = ", ".join(sorted({e.source for e in deduped}))
        reasoning = f"{'; '.join(reasoning_parts)}. Verified sources: [{sources_summary}]."
        return deduped, reasoning

    def collect_plan_evidence(self, app: ApplicationModel, test_case_evidence: List[List[Evidence]]) -> List[Evidence]:
        """
        Aggregates and deduplicates evidence across all generated test cases and application-level detections.
        """
        if app is None or not isinstance(app, ApplicationModel):
            raise InvalidInputError("collect_plan_evidence requires a valid ApplicationModel.")

        combined: List[Evidence] = []
        for ev_list in test_case_evidence:
            combined.extend(ev_list)

        for tech in app.technologies:
            for ev in tech.evidence:
                if ev.source and ev.type and ev.detail:
                    combined.append(ev)

        for svc in app.services:
            for ev in svc.evidence:
                if ev.source and ev.type and ev.detail:
                    combined.append(ev)

        if not combined:
            return []
        return self.deduplicate_evidence(combined)
