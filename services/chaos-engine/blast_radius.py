"""Blast-Radius Assessment & Enforcement for CHAOS-INTEL Phase 3C.

Evaluates the declared and topological blast radius of an `ExperimentSpecification`
against `ApplicationModel` architecture graphs and `PolicyConstants.BLAST_RADIUS_LIMITS`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Set
from pydantic import BaseModel, Field

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.models.application import ApplicationModel
from src.models.experiment import ExperimentSpecification
from src.safety.policy import PolicyConstants


class BlastRadiusLimitError(ValueError):
    """Raised when an experiment's blast radius violates policy or topological bounds."""


class BlastRadiusAssessment(BaseModel):
    """Structured result of evaluating an experiment's blast radius."""

    experiment_id: str
    application_id: str
    target_id: str
    target_type: str
    declared_scope: str
    declared_max_affected_components: int
    policy_max_allowed_components: int
    directly_affected_components: List[str] = Field(default_factory=list)
    transitively_impacted_callers: List[str] = Field(default_factory=list)
    hits_single_point_of_failure: bool = False
    within_limits: bool = True
    violations: List[str] = Field(default_factory=list)


class BlastRadiusAnalyzer:
    """Computes and enforces blast-radius limits for chaos experiments."""

    def __init__(self, scope_limits: Dict[str, int] | None = None) -> None:
        self.scope_limits: Dict[str, int] = dict(
            scope_limits if scope_limits is not None else PolicyConstants.BLAST_RADIUS_LIMITS
        )

    def assess(
        self,
        spec: ExperimentSpecification,
        app: ApplicationModel,
        *,
        enforce: bool = False,
    ) -> BlastRadiusAssessment:
        scope = str(spec.blast_radius.scope or "unknown")
        declared_max = int(spec.blast_radius.max_affected_components)
        policy_limit = int(self.scope_limits.get(scope, 0))
        violations: List[str] = []

        if scope == "unknown" or scope not in self.scope_limits:
            violations.append(f"Blast radius scope '{scope}' is unknown or unsupported.")

        if declared_max <= 0:
            violations.append(
                f"Declared max_affected_components ({declared_max}) must be >= 1."
            )

        if declared_max > policy_limit:
            violations.append(
                f"Declared max_affected_components ({declared_max}) exceeds policy limit ({policy_limit}) for scope '{scope}'."
            )

        # Discover directly affected target components in ApplicationModel
        direct: List[str] = [spec.target.id]
        extra_targets = spec.metadata.get("additional_targets", []) if isinstance(spec.metadata, dict) else []
        for t_id in extra_targets:
            if str(t_id) not in direct:
                direct.append(str(t_id))

        if len(direct) > declared_max:
            violations.append(
                f"Directly targeted components ({len(direct)}: {direct}) exceed declared max_affected_components ({declared_max})."
            )
        if len(direct) > policy_limit:
            violations.append(
                f"Directly targeted components ({len(direct)}) exceed policy limit ({policy_limit}) for scope '{scope}'."
            )

        # Compute upstream callers transitively impacted in architecture graph
        reverse_adj: Dict[str, Set[str]] = {}
        if app.architecture and app.architecture.edges:
            # Map graph node IDs onto component IDs (service_id when available) so graph edges
            # and experiment targets share one identifier space.
            node_to_component: Dict[str, str] = {
                n.node_id: (n.service_id or n.node_id) for n in (app.architecture.nodes or [])
            }
            for edge in app.architecture.edges:
                src = node_to_component.get(edge.source_node_id, edge.source_node_id)
                dst = node_to_component.get(edge.target_node_id, edge.target_node_id)
                reverse_adj.setdefault(dst, set()).add(src)
        for dep in app.dependencies or []:
            dep_target = dep.target_service_id or dep.name
            if dep_target and dep.source_service_id:
                reverse_adj.setdefault(dep_target, set()).add(dep.source_service_id)

        visited_callers: Set[str] = set()
        queue: List[str] = list(direct)
        while queue:
            curr = queue.pop(0)
            for caller in sorted(reverse_adj.get(curr, set())):
                if caller not in visited_callers and caller not in direct:
                    visited_callers.add(caller)
                    queue.append(caller)

        # Check if target is flagged as a Single Point of Failure (SPOF) in app risks
        hits_spof = False
        for risk in app.risks or []:
            kind = f"{risk.category} {risk.risk_type}".lower()
            if ("spof" in kind or "single_point_of_failure" in kind) and risk.target_id in (
                spec.target.id,
                spec.target.name,
            ):
                hits_spof = True
                break

        within_limits = len(violations) == 0
        assessment = BlastRadiusAssessment(
            experiment_id=spec.experiment_id,
            application_id=app.application_id,
            target_id=spec.target.id,
            target_type=spec.target.type,
            declared_scope=scope,
            declared_max_affected_components=declared_max,
            policy_max_allowed_components=policy_limit,
            directly_affected_components=direct,
            transitively_impacted_callers=sorted(visited_callers),
            hits_single_point_of_failure=hits_spof,
            within_limits=within_limits,
            violations=violations,
        )

        if enforce and not within_limits:
            raise BlastRadiusLimitError("; ".join(violations))

        return assessment

