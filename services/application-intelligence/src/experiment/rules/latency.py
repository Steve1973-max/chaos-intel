from typing import List
from ..base import ExperimentRule
from ...models.application import ApplicationModel
from ...models.experiment import ExperimentSpecification, Target, Fault
from ..defaults import get_default_blast_radius, get_default_steady_state, get_default_abort_conditions, get_default_rollback, get_default_safety

class LatencyExperimentRule(ExperimentRule):
    @property
    def rule_id(self) -> str:
        return "exp-lat"

    def generate(self, app: ApplicationModel) -> List[ExperimentSpecification]:
        experiments = []
        for cand in app.test_candidates:
            if cand.test_type == "latency":
                target = Target(type="unknown", id=cand.target_id, name=cand.target_id)
                fault = Fault(type="latency", method="network_delay", parameters={"delay_ms": 200})
                
                exp = ExperimentSpecification(
                    experiment_id=self.generate_experiment_id(app.application_id, fault.type, target.id),
                    application_id=app.application_id,
                    candidate_ids=[cand.candidate_id],
                    name=f"Network latency injection for {target.name}",
                    hypothesis=f"Experiment designed to evaluate application behavior when {target.name} experiences latency.",
                    status="requires_review", # usually unknown targets or need to review parameters
                    target=target,
                    fault=fault,
                    duration_seconds=60,
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
