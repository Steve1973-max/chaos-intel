"""Unified Failure Intelligence & Experiment Analysis for CHAOS-INTEL Phase 4.

Connects:
- Application Intelligence: architecture graph, dependencies, APIs, risks
- Testing Agents: test execution results, step failures, latency measurements
- Chaos Engine: experiment reports, OTel spans/metrics, abort records, audit trails
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"

if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.models.application import ApplicationModel

from analysis.dependency_impact_analyzer import DependencyImpactAnalyzer
from analysis.evidence_ranker import EvidenceRanker
from analysis.failure_classifier import FailureClassifier
from analysis.failure_correlator import FailureCorrelator
from analysis.recommendation_engine import RecommendationEngine
from analysis.root_cause_analyzer import RootCauseAnalyzer
from anomaly.engine import AnomalyDetectionEngine
from schemas.anomaly import Anomaly
from schemas.finding import CorrelatedFailureCluster, DependencyImpact, RootCauseHypothesis
from schemas.recommendation import ActionableRecommendation
from schemas.report import UnifiedExperimentAnalysis, utcnow_iso
from schemas.telemetry import NormalizedMetricPoint, StructuredLogEntry, TraceSpan
from telemetry.ingestor import TelemetryIngestor


class UnifiedFailureAnalyzer:
    """Unified subsystem correlating multi-source experiment telemetry into actionable intelligence."""

    def __init__(
        self,
        ingestor: Optional[TelemetryIngestor] = None,
        anomaly_engine: Optional[AnomalyDetectionEngine] = None,
        correlator: Optional[FailureCorrelator] = None,
        impact_analyzer: Optional[DependencyImpactAnalyzer] = None,
        classifier: Optional[FailureClassifier] = None,
        root_cause_analyzer: Optional[RootCauseAnalyzer] = None,
        evidence_ranker: Optional[EvidenceRanker] = None,
        recommendation_engine: Optional[RecommendationEngine] = None,
    ) -> None:
        self.ingestor = ingestor or TelemetryIngestor()
        self.anomaly_engine = anomaly_engine or AnomalyDetectionEngine()
        self.correlator = correlator or FailureCorrelator()
        self.impact_analyzer = impact_analyzer or DependencyImpactAnalyzer()
        self.classifier = classifier or FailureClassifier()
        self.root_cause_analyzer = root_cause_analyzer or RootCauseAnalyzer(classifier=self.classifier)
        self.evidence_ranker = evidence_ranker or EvidenceRanker()
        self.recommendation_engine = recommendation_engine or RecommendationEngine()

    def analyze_experiment(
        self,
        app: ApplicationModel,
        chaos_report: Optional[Any] = None,
        test_results: Optional[List[Any]] = None,
        additional_metrics: Optional[List[NormalizedMetricPoint]] = None,
        additional_logs: Optional[List[StructuredLogEntry | Dict[str, Any] | str]] = None,
        additional_spans: Optional[List[TraceSpan]] = None,
        correlation_id_override: Optional[str] = None,
    ) -> UnifiedExperimentAnalysis:
        """Produce unified experiment analysis integrating all multi-agent observations."""
        analysis_id = f"fa-{uuid.uuid4().hex[:12]}"

        # Extract correlation ID and experiment ID
        exp_id = getattr(chaos_report, "experiment_id", "unknown-experiment")
        corr_id = (
            correlation_id_override
            or getattr(chaos_report, "correlation_id", None)
            or (test_results[0].correlation_id if test_results and getattr(test_results[0], "correlation_id", None) else f"corr-{uuid.uuid4().hex[:8]}")
        )
        app_id = app.application_id

        # -------------------------------------------------------------
        # STEP 1: Ingest & Normalize Telemetry from Chaos Engine
        # -------------------------------------------------------------
        baseline_points: List[NormalizedMetricPoint] = []
        obs_points: List[NormalizedMetricPoint] = []
        timeline: List[Dict[str, Any]] = []

        if chaos_report is not None:
            # Baseline metrics
            obs_rec = getattr(chaos_report, "observation", None)
            if obs_rec is not None and getattr(obs_rec, "baseline_snapshot", None):
                base_snap = obs_rec.baseline_snapshot
                ts = base_snap.timestamp or utcnow_iso()
                for k, v in base_snap.metrics.items():
                    norm_pt = NormalizedMetricPoint(
                        metric_name=f"app.{k}" if not k.startswith("infra.") else k,
                        category="application" if "error" in k or "latency" in k or "avail" in k else "infrastructure",
                        service_id=chaos_report.target_id,
                        timestamp=ts,
                        value=float(v),
                        unit="1" if "rate" in k or "avail" in k else ("ms" if "latency" in k else "%"),
                    )
                    baseline_points.append(norm_pt)
                    self.ingestor.ingest_metric_point(norm_pt)

            # Observation metrics and deltas
            if obs_rec is not None and getattr(obs_rec, "observation_snapshots", None):
                for snap in obs_rec.observation_snapshots:
                    ts = snap.timestamp or utcnow_iso()
                    for k, v in snap.metrics.items():
                        norm_pt = NormalizedMetricPoint(
                            metric_name=f"app.{k}" if not k.startswith("infra.") else k,
                            category="application" if "error" in k or "latency" in k or "avail" in k else "infrastructure",
                            service_id=chaos_report.target_id,
                            timestamp=ts,
                            value=float(v),
                            unit="1" if "rate" in k or "avail" in k else ("ms" if "latency" in k else "%"),
                        )
                        obs_points.append(norm_pt)
                        self.ingestor.ingest_metric_point(norm_pt)

            # OpenTelemetry Spans and Metrics from Chaos Engine
            if obs_rec is not None and getattr(obs_rec, "otel_spans", None):
                for span_rec in obs_rec.otel_spans:
                    span = TraceSpan(
                        trace_id=span_rec.trace_id,
                        span_id=span_rec.span_id,
                        parent_span_id=span_rec.parent_span_id,
                        service_id=chaos_report.target_id,
                        operation_name=span_rec.name,
                        start_time=span_rec.start_time,
                        end_time=span_rec.end_time,
                        duration_ms=0.0,
                        status_code="OK" if span_rec.status_code == "OK" else "ERROR",
                        attributes=span_rec.attributes,
                    )
                    self.ingestor.ingest_span(span)

            # Record timeline event for fault injection
            timeline.append({
                "timestamp": getattr(chaos_report, "generated_at", utcnow_iso()),
                "event_type": "chaos_experiment_executed",
                "service_id": chaos_report.target_id,
                "detail": f"Fault '{chaos_report.fault_type}' executed on '{chaos_report.target_id}'. Verdict: {chaos_report.verdict}",
            })

            # Check abort event
            if getattr(chaos_report, "abort", None) and chaos_report.abort.triggered:
                timeline.append({
                    "timestamp": utcnow_iso(),
                    "event_type": "safety_abort_triggered",
                    "service_id": chaos_report.target_id,
                    "detail": f"Emergency abort triggered by {chaos_report.abort.source}: {chaos_report.abort.reason}",
                })

        # Ingest additional metrics/logs/spans
        if additional_metrics:
            for p in additional_metrics:
                obs_points.append(p)
                self.ingestor.ingest_metric_point(p)

        if additional_logs:
            for l in additional_logs:
                if isinstance(l, StructuredLogEntry):
                    self.ingestor._logs.append(l)
                else:
                    self.ingestor.ingest_log(l)

        if additional_spans:
            for s in additional_spans:
                self.ingestor.ingest_span(s)

        # -------------------------------------------------------------
        # STEP 2: Ingest Test Execution Results from Testing Agents
        # -------------------------------------------------------------
        test_failure_dicts: List[Dict[str, Any]] = []
        if test_results:
            for tr in test_results:
                status = getattr(tr, "status", "unknown")
                if status in ("failed", "timed_out", "error"):
                    err_dtl = getattr(tr, "error_details", None)
                    if isinstance(err_dtl, dict):
                        err_msg = err_dtl.get("error_message") or err_dtl.get("message") or ""
                    elif err_dtl is not None:
                        err_msg = getattr(err_dtl, "error_message", str(err_dtl))
                    else:
                        err_msg = str(getattr(tr, "error", ""))
                    t_fail = {
                        "execution_id": getattr(tr, "execution_id", "unknown"),
                        "test_case_id": getattr(tr, "test_case_id", "unknown"),
                        "service_id": getattr(tr, "target_service_id", getattr(chaos_report, "target_id", "unknown")),
                        "status": status,
                        "error_message": err_msg,
                        "ended_at": getattr(tr, "ended_at", utcnow_iso()),
                    }
                    test_failure_dicts.append(t_fail)
                    timeline.append({
                        "timestamp": getattr(tr, "ended_at", utcnow_iso()),
                        "event_type": "test_failure_observed",
                        "service_id": t_fail["service_id"],
                        "detail": f"Test case '{t_fail['test_case_id']}' failed: {t_fail['error_message']}",
                    })

        # -------------------------------------------------------------
        # STEP 3: Anomaly Detection
        # -------------------------------------------------------------
        detected_anomalies = self.anomaly_engine.detect_anomalies(
            points=obs_points or self.ingestor.get_metrics(),
            baseline_points=baseline_points,
        )

        for anom in detected_anomalies:
            timeline.append({
                "timestamp": anom.timestamp,
                "event_type": "anomaly_detected",
                "service_id": anom.affected_service,
                "detail": f"[{anom.severity.upper()}] Anomaly on '{anom.metric}': observed={anom.observed_value} (baseline={anom.baseline_value}, dev={anom.deviation_percentage}%)",
            })

        # -------------------------------------------------------------
        # STEP 4: Correlation & Clustering
        # -------------------------------------------------------------
        error_logs = self.ingestor.log_processor.filter_errors(self.ingestor.get_logs())
        error_spans = self.ingestor.trace_processor.find_error_traces()
        raw_error_spans = [s for t in error_spans for s in t.error_spans]

        chaos_events: List[Dict[str, Any]] = []
        if chaos_report is not None:
            chaos_events.append({
                "experiment_id": exp_id,
                "fault_type": chaos_report.fault_type,
                "target_id": chaos_report.target_id,
                "verdict": chaos_report.verdict,
                "timestamp": getattr(chaos_report, "generated_at", utcnow_iso()),
            })

        clusters: List[CorrelatedFailureCluster] = self.correlator.correlate(
            correlation_id=corr_id,
            anomalies=detected_anomalies,
            error_logs=error_logs,
            error_spans=raw_error_spans,
            test_failures=test_failure_dicts,
            chaos_events=chaos_events,
        )

        primary_cluster = clusters[0] if clusters else CorrelatedFailureCluster(
            cluster_id=f"cluster-{uuid.uuid4().hex[:8]}",
            correlation_id=corr_id,
            time_window_start=utcnow_iso(),
            time_window_end=utcnow_iso(),
            primary_affected_service=getattr(chaos_report, "target_id", "unknown"),
        )

        # -------------------------------------------------------------
        # STEP 5: Dependency Impact Analysis
        # -------------------------------------------------------------
        dep_impact: DependencyImpact = self.impact_analyzer.analyze(
            root_service_id=primary_cluster.primary_affected_service,
            app=app,
            observed_failing_services=primary_cluster.affected_services,
        )

        # -------------------------------------------------------------
        # STEP 6: Root Cause Analysis (Competing Hypotheses)
        # -------------------------------------------------------------
        root_causes: List[RootCauseHypothesis] = self.root_cause_analyzer.analyze_root_causes(
            cluster=primary_cluster,
            dependency_impact=dep_impact,
            all_candidate_services=primary_cluster.affected_services,
        )

        # -------------------------------------------------------------
        # STEP 7: Evidence Ranking
        # -------------------------------------------------------------
        raw_evidence: List[Dict[str, Any]] = []
        for rc in root_causes:
            raw_evidence.extend(rc.supporting_evidence)
            raw_evidence.extend(rc.conflicting_evidence)
        for anom in detected_anomalies:
            raw_evidence.extend(anom.evidence_references)

        ranked_evidence = self.evidence_ranker.rank_evidence(raw_evidence)

        # -------------------------------------------------------------
        # STEP 8: Recommendation Generation
        # -------------------------------------------------------------
        recommendations: List[ActionableRecommendation] = self.recommendation_engine.generate_recommendations(
            root_causes=root_causes,
            dependency_impact=dep_impact,
            correlation_id=corr_id,
        )

        # Sort timeline chronologically
        timeline.sort(key=lambda item: item.get("timestamp", ""))

        # Recovery behavior summary
        recovery_behavior: Dict[str, Any] = {
            "recovery_status": getattr(chaos_report, "final_lifecycle_state", "UNKNOWN"),
            "recovery_classification": getattr(chaos_report, "recovery_classification", "unknown"),
            "hypothesis_held": getattr(chaos_report, "hypothesis_held", None),
            "steady_state_restored": getattr(chaos_report, "final_lifecycle_state", "") == "COMPLETED",
        }
        if chaos_report and getattr(chaos_report, "observation", None):
            obs = chaos_report.observation
            if getattr(obs, "recovery_duration_ms", None) is not None:
                recovery_behavior["recovery_duration_ms"] = obs.recovery_duration_ms

        # Baseline health summary
        baseline_health: Dict[str, Any] = {}
        for bp in baseline_points:
            baseline_health[bp.metric_name] = bp.value

        return UnifiedExperimentAnalysis(
            analysis_id=analysis_id,
            experiment_id=exp_id,
            application_id=app_id,
            correlation_id=corr_id,
            baseline_health=baseline_health,
            observed_anomalies=detected_anomalies,
            affected_services=sorted(primary_cluster.affected_services or [primary_cluster.primary_affected_service]),
            failure_timeline=timeline,
            dependency_impact=dep_impact,
            probable_root_causes=root_causes,
            recovery_behavior=recovery_behavior,
            recommendations=recommendations,
            evidence_chain=[e.to_dict() for e in ranked_evidence],
            metadata={
                "cluster_id": primary_cluster.cluster_id,
                "anomalies_detected": len(detected_anomalies),
                "hypotheses_generated": len(root_causes),
                "recommendations_generated": len(recommendations),
            },
        )
