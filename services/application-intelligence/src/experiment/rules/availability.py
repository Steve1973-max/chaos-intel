from typing import List
from ..base import ExperimentRule
from ...models.application import ApplicationModel
from ...models.experiment import ExperimentSpecification, Target, Fault
from ..defaults import get_default_blast_radius, get_default_steady_state, get_default_abort_conditions, get_default_rollback, get_default_safety

class AvailabilityExperimentRule(ExperimentRule):
    @property
    def rule_id(self) -> str:
        return "exp-avail"

    def generate(self, app: ApplicationModel) -> List[ExperimentSpecification]:
        experiments = []
        for cand in app.test_candidates:
            if cand.test_type in ("availability", "failover"):
                # Define status and target
                status = "draft" if cand.target_id else "requires_review"
                # Target type resolution: if we know it's a service vs dependency vs unknown
                t_type = "unknown"
                for n in app.architecture.nodes:
                    if n.node_id == cand.target_id or n.name == cand.target_id:
                        if n.node_type in ("frontend", "backend", "worker", "service"):
                            t_type = "service"
                        else:
                            t_type = n.node_type
                
                target = Target(type=t_type, id=cand.target_id, name=cand.target_id)
                purpose = "failover_validation" if cand.test_type == "failover" else None
                fault = Fault(type="availability", method="service_stop", purpose=purpose)
                
                exp = ExperimentSpecification(
                    experiment_id=self.generate_experiment_id(app.application_id, fault.type, target.id),
                    application_id=app.application_id,
                    candidate_ids=[cand.candidate_id],
                    name=f"Validate {cand.test_type} of {target.name}",
                    hypothesis=f"Experiment designed to evaluate application behavior when {target.name} becomes unavailable.",
                    status=status,
                    target=target,
                    fault=fault,
                    duration_seconds=30,
                    blast_radius=get_default_blast_radius(),
                    steady_state=get_default_steady_state(),
                    observations=list(cand.suggested_observations),
                    abort_conditions=get_default_abort_conditions(),
                    rollback=get_default_rollback(),
                    prerequisites=list(cand.prerequisites),
                    safety=get_default_safety(),
                    confidence=cand.confidence,
                    evidence=list(cand.evidence)
                )
                experiments.append(exp)
        return experiments
