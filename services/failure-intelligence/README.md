# CHAOS-INTEL — Phase 4: Observability & Failure Intelligence

A unified observability and failure-intelligence subsystem that ingests multi-modal telemetry, detects multi-algorithm anomalies, correlates temporal-topological system behavior, identifies probable root causes through competing hypotheses, traces cascading dependency impact, and generates evidence-backed, actionable remediation recommendations.

## Core Capabilities

1. **Multi-Modal Telemetry & Ingestion (`telemetry/`)**
   - Normalizes Infrastructure, Application, and Resilience metrics into unified `NormalizedMetricPoint` series.
   - Time-series alignment, sampling, and non-hallucinating missing-data resolution (`drop`, `forward_fill`, `linear_interpolate`, `explicit_marker`).
   - Structured logging parser (`StructuredLogEntry`) with log-level filtering and automatic error type classification.
   - Distributed tracing indexer (`TraceProcessor`) building span hierarchies, calculating latency bottlenecks, and mapping error traces.
   - Service and dependency resilience health evaluator (`HealthMonitor`).
   - Integration interfaces and formatters for OpenTelemetry (OTLP JSON), Prometheus (text exposition), Grafana (dashboards), Loki (log push), and Tempo (trace push).

2. **Multi-Algorithm Anomaly Detection Engine (`anomaly/`)**
   - **Threshold-based**: static and dynamic threshold boundaries.
   - **Moving average divergence**: SMA and EMA deviation tracking.
   - **Statistical deviation**: Z-score and Interquartile Range (IQR) detection.
   - **Pattern-specific detectors**: Latency spikes, Error-rate surges, Availability degradation, and Resource saturation streaks.
   - Model-agnostic detector interface (`AnomalyDetector`) for deterministic algorithms and future ML models.

3. **Failure Intelligence Engine (`analysis/`)**
   - **Failure Correlator (`failure_correlator.py`)**: Correlates multi-source events (metrics, logs, traces, test failures, chaos events) into temporal clusters.
   - **Dependency Impact Analyzer (`dependency_impact_analyzer.py`)**: Traverses `ApplicationModel` call graphs to map affected downstream services, APIs, and cascading failures.
   - **Failure Classifier (`failure_classifier.py`)**: Categorizes failures into 7 standard categories (Infrastructure, Network, Application, Database, Dependency, Configuration, Resource Exhaustion).
   - **Root Cause Analyzer (`root_cause_analyzer.py`)**: Ranks multiple competing root-cause hypotheses using temporal precedence and graph topology, strictly distinguishing observed facts from inferred causes (`is_causation_proven = False`).
   - **Evidence Ranker (`evidence_ranker.py`)**: Evaluates evidence credibility weights, deduplicates references, and notes conflicting/missing evidence.
   - **Recommendation Engine (`recommendation_engine.py`)**: Emits actionable remediation recommendations with concrete remediation steps, priority, and confidence.

4. **Unified Experiment Analysis (`unified_analyzer.py`)**
   - Seamlessly integrates Application Intelligence models (`ApplicationModel`), Testing Agents results (`TestExecutionResult`), and Chaos Engine outcomes (`ChaosExperimentReport`) into a comprehensive `UnifiedExperimentAnalysis` report.

