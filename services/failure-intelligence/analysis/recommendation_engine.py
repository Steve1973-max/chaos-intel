"""Evidence-backed Recommendation Engine for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Optional
from schemas.finding import DependencyImpact, RootCauseHypothesis
from schemas.recommendation import (
    ActionableRecommendation,
    RecommendationCategory,
    RecommendationPriority,
)


class RecommendationEngine:
    """Generates evidence-backed, actionable remediation recommendations."""

    def generate_recommendations(
        self,
        root_causes: List[RootCauseHypothesis],
        dependency_impact: Optional[DependencyImpact] = None,
        correlation_id: Optional[str] = None,
    ) -> List[ActionableRecommendation]:
        """Generate concrete architectural and resilience recommendations for identified root causes."""
        recommendations: List[ActionableRecommendation] = []
        if not root_causes:
            return recommendations

        # Primary root cause hypothesis
        primary = root_causes[0]
        svc = primary.probable_root_cause_service
        cat = primary.failure_category
        conf = primary.confidence

        ev_ids: List[str] = [
            f"ev-sup-{idx}" for idx in range(min(5, len(primary.supporting_evidence)))
        ]

        # 1. Category-specific recommendations
        if cat in ("ResourceExhaustion", "Infrastructure"):
            rec_id = f"rec-res-{uuid.uuid4().hex[:8]}"
            priority: RecommendationPriority = "critical" if conf >= 0.8 else "high"
            recommendations.append(
                ActionableRecommendation(
                    recommendation_id=rec_id,
                    category="capacity",
                    priority=priority,
                    title=f"Adjust resource limits and configure horizontal pod auto-scaling for '{svc}'",
                    description=(
                        f"Target service '{svc}' exhibited resource saturation under fault injection/load. "
                        f"Configure container CPU/memory requests and limits, and enable horizontal auto-scaling (HPA) "
                        f"with a target utilization threshold of 75% to prevent ungraceful process termination."
                    ),
                    target_service=svc,
                    confidence=conf,
                    supporting_evidence_ids=ev_ids,
                    remediation_steps=[
                        f"Review and increase memory/CPU limits in service '{svc}' deployment manifest.",
                        "Configure Kubernetes Horizontal Pod Autoscaler (HPA) to scale at >= 75% utilization.",
                        "Implement readiness and liveness probe timeouts to avoid prematurely restarting saturated pods.",
                    ],
                    estimated_risk_reduction="high",
                    metadata={"category": cat, "confidence": conf},
                )
            )

        elif cat in ("Network", "Dependency"):
            rec_id = f"rec-cb-{uuid.uuid4().hex[:8]}"
            priority: RecommendationPriority = "high"
            callers = dependency_impact.downstream_impacted_services if dependency_impact else []
            caller_str = f"callers ({', '.join(callers[:2])})" if callers else "downstream callers"

            recommendations.append(
                ActionableRecommendation(
                    recommendation_id=rec_id,
                    category="circuit_breaker",
                    priority=priority,
                    title=f"Implement circuit breakers and exponential backoff on calls to '{svc}'",
                    description=(
                        f"Network partition or latency injected against '{svc}' cascaded to {caller_str}. "
                        f"Wrap remote client calls with a circuit breaker pattern (trip on 5 consecutive failures, "
                        f"30s cooldown) and bounded exponential backoff with full jitter to halt cascading failures."
                    ),
                    target_service=svc,
                    confidence=conf,
                    supporting_evidence_ids=ev_ids,
                    remediation_steps=[
                        f"Introduce Resilience4j / Polly / Envoy circuit breaker on inbound clients calling '{svc}'.",
                        "Set maximum client HTTP request timeout to <= 2.5 seconds.",
                        "Configure fallback responses (e.g. cached data or graceful degradation message) when breaker trips.",
                    ],
                    estimated_risk_reduction="high",
                    metadata={"category": cat, "downstream_callers": callers},
                )
            )

        elif cat == "Database":
            rec_id = f"rec-db-{uuid.uuid4().hex[:8]}"
            recommendations.append(
                ActionableRecommendation(
                    recommendation_id=rec_id,
                    category="database_tuning",
                    priority="high",
                    title=f"Configure connection pooling and read replicas for database service '{svc}'",
                    description=(
                        f"Database connectivity degradation on '{svc}' directly triggered application error spikes. "
                        f"Ensure connection pool size is bounded (max 50 connections), configure query statement timeouts "
                        f"(<= 2000ms), and route idempotent queries to read replicas."
                    ),
                    target_service=svc,
                    confidence=conf,
                    supporting_evidence_ids=ev_ids,
                    remediation_steps=[
                        "Tune connection pool idle and maximum lifetime settings.",
                        "Configure statement timeout of 2000ms in database connection pool configuration.",
                        "Deploy database read replicas and verify read/write connection separation.",
                    ],
                    estimated_risk_reduction="high",
                    metadata={"category": cat},
                )
            )

        else:
            rec_id = f"rec-app-{uuid.uuid4().hex[:8]}"
            recommendations.append(
                ActionableRecommendation(
                    recommendation_id=rec_id,
                    category="resilience",
                    priority="medium",
                    title=f"Introduce structured error boundaries and retry policies for '{svc}'",
                    description=(
                        f"Application logic or uncaught exceptions in '{svc}' disrupted request processing. "
                        f"Add global error handling middleware, return structured RFC 7807 problem details, "
                        f"and isolate unhandled exceptions to avoid whole-worker crashes."
                    ),
                    target_service=svc,
                    confidence=conf,
                    supporting_evidence_ids=ev_ids,
                    remediation_steps=[
                        "Add unhandled exception middleware in service HTTP pipeline.",
                        "Validate input parameters before invoking downstream business logic.",
                        "Implement health-check endpoint that tests internal dependency reachability.",
                    ],
                    estimated_risk_reduction="medium",
                    metadata={"category": cat},
                )
            )

        # 2. Add redundancy/SPOF recommendation if blast radius is high
        if dependency_impact and (len(dependency_impact.downstream_impacted_services) >= 2 or dependency_impact.cascading_failure):
            rec_spof_id = f"rec-spof-{uuid.uuid4().hex[:8]}"
            recommendations.append(
                ActionableRecommendation(
                    recommendation_id=rec_spof_id,
                    category="redundancy",
                    priority="critical" if dependency_impact.cascading_failure else "high",
                    title=f"Eliminate single-point-of-failure and isolate blast radius for '{svc}'",
                    description=(
                        f"Failure in '{svc}' cascaded to {len(dependency_impact.downstream_impacted_services)} services "
                        f"({', '.join(dependency_impact.downstream_impacted_services)}). "
                        f"Deploy multi-instance active-active redundancy with health-gated load balancing."
                    ),
                    target_service=svc,
                    confidence=0.88,
                    supporting_evidence_ids=ev_ids,
                    remediation_steps=[
                        f"Deploy minimum of 2 replicas across distinct availability zones for '{svc}'.",
                        "Configure health probes to automatically drain traffic away from degraded instances.",
                        "Implement bulkhead isolation to prevent worker thread pool exhaustion in callers.",
                    ],
                    estimated_risk_reduction="critical",
                    metadata={"cascading": dependency_impact.cascading_failure},
                )
            )

        return recommendations

