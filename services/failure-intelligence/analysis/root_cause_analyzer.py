"""Probable Root Cause Analyzer for CHAOS-INTEL Phase 4.

Strictly distinguishes observed facts from inferred causes.
Produces multiple competing hypotheses with confidence ranking and evidence chains.
Never claims correlation as proven causation (is_causation_proven = False).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from analysis.failure_classifier import FailureClassifier
from schemas.anomaly import Anomaly
from schemas.finding import CorrelatedFailureCluster, DependencyImpact, RootCauseHypothesis


def parse_iso_epoch(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


class RootCauseAnalyzer:
    """Analyzes temporal precedence and topological dependencies to rank root-cause hypotheses."""

    def __init__(self, classifier: Optional[FailureClassifier] = None) -> None:
        self.classifier = classifier or FailureClassifier()

    def analyze_root_causes(
        self,
        cluster: CorrelatedFailureCluster,
        dependency_impact: Optional[DependencyImpact] = None,
        all_candidate_services: Optional[List[str]] = None,
    ) -> List[RootCauseHypothesis]:
        """Generate, evaluate, and rank competing root-cause hypotheses."""
        hypotheses: List[RootCauseHypothesis] = []
        classification = self.classifier.classify(cluster)

        # 1. Identify services with earliest anomaly or failure event (temporal precedence)
        first_event_times: Dict[str, float] = {}
        for anom in cluster.anomalies:
            t = parse_iso_epoch(anom.timestamp)
            if anom.affected_service not in first_event_times or t < first_event_times[anom.affected_service]:
                first_event_times[anom.affected_service] = t

        for log in cluster.error_logs:
            t = parse_iso_epoch(log.timestamp)
            if log.service_id not in first_event_times or t < first_event_times[log.service_id]:
                first_event_times[log.service_id] = t

        for span in cluster.error_spans:
            t = parse_iso_epoch(span.start_time)
            if span.service_id not in first_event_times or t < first_event_times[span.service_id]:
                first_event_times[span.service_id] = t

        # Chronological candidate ranking
        sorted_by_time = sorted(first_event_times.items(), key=lambda item: item[1])

        # Candidate services to evaluate
        candidate_services: List[str] = []
        # Priority 1: explicitly targeted chaos service
        if cluster.chaos_events:
            for ce in cluster.chaos_events:
                tgt = ce.get("target_id")
                if tgt and tgt not in candidate_services:
                    candidate_services.append(tgt)

        # Priority 2: temporal earliest failing services
        for s, _ in sorted_by_time:
            if s not in candidate_services:
                candidate_services.append(s)

        # Priority 3: any other affected service
        for s in cluster.affected_services:
            if s not in candidate_services:
                candidate_services.append(s)

        if not candidate_services:
            candidate_services = [cluster.primary_affected_service]

        # 2. Build competing hypotheses for candidates
        for idx, svc in enumerate(candidate_services[:3]):  # Top 3 competing hypotheses
            supporting_evidence: List[Dict[str, Any]] = []
            conflicting_evidence: List[Dict[str, Any]] = []
            missing_evidence: List[str] = []

            # Check chaos alignment
            has_chaos = any(ce.get("target_id") == svc for ce in cluster.chaos_events)
            if has_chaos:
                supporting_evidence.append({
                    "type": "chaos_injection_target",
                    "detail": f"Target service '{svc}' received explicit chaos fault injection during experiment window.",
                })

            # Check temporal precedence
            if sorted_by_time and sorted_by_time[0][0] == svc:
                supporting_evidence.append({
                    "type": "temporal_precedence",
                    "detail": f"Service '{svc}' experienced the earliest recorded anomaly or error in the cluster.",
                })
            elif sorted_by_time and sorted_by_time[0][0] != svc:
                conflicting_evidence.append({
                    "type": "temporal_lag",
                    "detail": f"Service '{sorted_by_time[0][0]}' exhibited errors before '{svc}', suggesting '{svc}' may be a secondary symptom.",
                })

            # Check topology position
            if dependency_impact:
                if svc == dependency_impact.root_service_id:
                    supporting_evidence.append({
                        "type": "topological_origin",
                        "detail": f"Service '{svc}' is positioned as the dependency root with downstream cascading impact.",
                    })
                elif svc in dependency_impact.downstream_impacted_services:
                    conflicting_evidence.append({
                        "type": "downstream_position",
                        "detail": f"Service '{svc}' is downstream of '{dependency_impact.root_service_id}', which could indicate caller-side ripple impact rather than root origin.",
                    })

            # Gather service-specific anomalies and logs
            svc_anomalies = [a for a in cluster.anomalies if a.affected_service == svc]
            svc_logs = [l for l in cluster.error_logs if l.service_id == svc]

            for a in svc_anomalies:
                supporting_evidence.append({
                    "type": "metric_anomaly",
                    "detail": f"Observed {a.severity} anomaly on '{a.metric}' (value={a.observed_value}, baseline={a.baseline_value}).",
                })

            for l in svc_logs:
                supporting_evidence.append({
                    "type": "error_log",
                    "detail": f"[{l.level}] {l.message[:100]}",
                })

            if not svc_logs and not svc_anomalies:
                missing_evidence.append(f"No direct metrics or error logs recorded for service '{svc}'.")

            # Calculate confidence: starting from classification confidence, adjusted for evidence balance
            score = 0.50
            if has_chaos:
                score += 0.30
            if sorted_by_time and sorted_by_time[0][0] == svc:
                score += 0.15
            if dependency_impact and svc == dependency_impact.root_service_id:
                score += 0.10
            if conflicting_evidence:
                score -= 0.15 * len(conflicting_evidence)

            conf = round(max(0.20, min(0.96, score)), 2)

            hyp_id = f"hyp-{hashlib.sha256(f'{cluster.cluster_id}:{svc}:{idx}'.encode()).hexdigest()[:8]}"
            title = f"Probable {classification.category} failure originating in '{svc}'"
            explanation = (
                f"Evidence indicates that service '{svc}' is the probable origin of the correlated failure cluster. "
                f"Observed {len(supporting_evidence)} supporting indicators. "
                + (f"Note: {len(conflicting_evidence)} conflicting temporal/topological factors observed." if conflicting_evidence else "")
            )

            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=hyp_id,
                    probable_root_cause_service=svc,
                    failure_category=classification.category,
                    title=title,
                    explanation=explanation,
                    confidence=conf,
                    rank=idx + 1,
                    is_causation_proven=False,  # strictly False per core intelligence requirement
                    supporting_evidence=supporting_evidence,
                    conflicting_evidence=conflicting_evidence,
                    missing_evidence=missing_evidence,
                    metadata={"classification_confidence": classification.confidence},
                )
            )

        # Sort hypotheses by confidence descending and re-rank
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        for r_idx, h in enumerate(hypotheses):
            h.rank = r_idx + 1

        return hypotheses

