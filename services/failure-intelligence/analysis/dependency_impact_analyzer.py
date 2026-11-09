"""Dependency Impact Analyzer for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.models.application import ApplicationModel
from schemas.finding import DependencyImpact


class DependencyImpactAnalyzer:
    """Analyzes failure propagation along architectural dependency graphs."""

    def analyze(
        self,
        root_service_id: str,
        app: ApplicationModel,
        observed_failing_services: Optional[List[str]] = None,
    ) -> DependencyImpact:
        """Trace downstream services and APIs affected by failure at root_service_id."""
        failing_set = set(observed_failing_services or [])
        failing_set.add(root_service_id)

        # Build forward adjacency list: caller -> callee, and dependency links
        forward_adj: Dict[str, Set[str]] = {}
        reverse_adj: Dict[str, Set[str]] = {}

        node_to_service: Dict[str, str] = {}
        if app.architecture and app.architecture.nodes:
            for n in app.architecture.nodes:
                node_to_service[n.node_id] = n.service_id or n.node_id

        if app.architecture and app.architecture.edges:
            for edge in app.architecture.edges:
                src = node_to_service.get(edge.source_node_id, edge.source_node_id)
                dst = node_to_service.get(edge.target_node_id, edge.target_node_id)
                forward_adj.setdefault(src, set()).add(dst)
                reverse_adj.setdefault(dst, set()).add(src)

        for dep in app.dependencies or []:
            src = dep.source_service_id
            dst = dep.target_service_id or dep.name
            if src and dst:
                forward_adj.setdefault(src, set()).add(dst)
                reverse_adj.setdefault(dst, set()).add(src)

        # Downstream callers impacted when target fails (callers that depend on target)
        downstream_callers: Set[str] = set()
        queue: List[str] = [root_service_id]
        propagation_path: List[str] = [root_service_id]

        while queue:
            curr = queue.pop(0)
            callers = sorted(reverse_adj.get(curr, set()))
            for c in callers:
                if c not in downstream_callers and c != root_service_id:
                    downstream_callers.add(c)
                    propagation_path.append(c)
                    queue.append(c)

        # Impacted APIs
        impacted_apis: List[str] = []
        affected_set = {root_service_id, *downstream_callers}
        for api in app.apis or []:
            api_target = getattr(api, "service_id", None) or getattr(api, "target_component_id", None)
            if api_target in affected_set:
                impacted_apis.append(f"{api.method} {api.path}")

        # Cascading failure: did errors propagate to at least one dependent caller?
        cascading = any(c in failing_set for c in downstream_callers)

        total_services = max(1, len(app.services) if app.services else len(node_to_service))
        blast_score = round(min(1.0, (1 + len(downstream_callers)) / total_services), 2)

        return DependencyImpact(
            root_service_id=root_service_id,
            directly_affected_services=[root_service_id],
            downstream_impacted_services=sorted(downstream_callers),
            impacted_apis=sorted(impacted_apis),
            cascading_failure=cascading,
            propagation_path=propagation_path,
            blast_radius_score=blast_score,
            metadata={
                "total_services_count": total_services,
                "callers_count": len(downstream_callers),
                "impacted_api_count": len(impacted_apis),
            },
        )
