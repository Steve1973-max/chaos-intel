"""Evidence Ranker and Conflict Evaluator for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple


class RankedEvidence:
    """Evidence item scored and ranked for confidence weighting."""

    def __init__(
        self,
        evidence_id: str,
        evidence_type: str,
        source: str,
        detail: str,
        weight: float,
        is_conflicting: bool = False,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        self.evidence_id = evidence_id
        self.evidence_type = evidence_type
        self.source = source
        self.detail = detail
        self.weight = weight
        self.is_conflicting = is_conflicting
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "source": self.source,
            "detail": self.detail,
            "weight": round(self.weight, 3),
            "is_conflicting": self.is_conflicting,
            "metadata": self.metadata,
        }


class EvidenceRanker:
    """Ranks, deduplicates, and evaluates confidence for empirical evidence."""

    SOURCE_WEIGHTS: Dict[str, float] = {
        "chaos_injection_target": 0.95,
        "metric_threshold_breach": 0.90,
        "resource_saturation": 0.92,
        "latency_spike_breach": 0.88,
        "error_rate_surge": 0.90,
        "availability_drop": 0.95,
        "error_log": 0.82,
        "trace_error_span": 0.85,
        "test_assertion_failure": 0.80,
        "temporal_precedence": 0.75,
        "topological_origin": 0.70,
        "circumstantial": 0.50,
    }

    def rank_evidence(self, raw_evidence: List[Dict[str, Any]]) -> List[RankedEvidence]:
        """Deduplicate, score, and rank evidence items in descending order of evidentiary weight."""
        deduped: Dict[str, RankedEvidence] = {}

        for item in raw_evidence:
            ev_type = str(item.get("type", "circumstantial"))
            detail = str(item.get("detail", ""))
            src = str(item.get("source", "telemetry"))
            is_conflict = bool(item.get("is_conflicting", False))

            base_wt = self.SOURCE_WEIGHTS.get(ev_type, 0.50)
            if is_conflict:
                base_wt = base_wt * 0.8  # slightly discounted for conflicting evidence

            # Deterministic evidence ID based on content
            ev_id = f"ev-{hashlib.sha256(f'{ev_type}:{detail}'.encode()).hexdigest()[:8]}"

            if ev_id not in deduped or deduped[ev_id].weight < base_wt:
                deduped[ev_id] = RankedEvidence(
                    evidence_id=ev_id,
                    evidence_type=ev_type,
                    source=src,
                    detail=detail,
                    weight=base_wt,
                    is_conflicting=is_conflict,
                    metadata=item.get("metadata", {}),
                )

        ranked = list(deduped.values())
        ranked.sort(key=lambda e: e.weight, reverse=True)
        return ranked

