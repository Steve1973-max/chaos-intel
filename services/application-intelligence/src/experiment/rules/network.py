from typing import List
from ..base import ExperimentRule
from ...models.application import ApplicationModel
from ...models.experiment import ExperimentSpecification, Target, Fault
from ..defaults import get_default_blast_radius, get_default_steady_state, get_default_abort_conditions, get_default_rollback, get_default_safety

class NetworkExperimentRule(ExperimentRule):
    @property
    def rule_id(self) -> str:
        return "exp-net"

    def generate(self, app: ApplicationModel) -> List[ExperimentSpecification]:
        experiments = []
        for cand in app.test_candidates:
            if cand.test_type in ("network_partition", "workflow_resilience"):
                target = Target(type="unknown", id=cand.target_id, name=cand.target_id)
                fault = Fault(type="network_partition", method="network_isolation")
                
                exp = ExperimentSpecification(
                    experiment_id=self.generate_experiment_id(app.application_id, fault.type, target.id),
                    application_id=app.application_id,
                    candidate_ids=[cand.candidate_id],
                    name=f"Network isolation for {target.name}",
                    hypothesis=f"Experiment designed to evaluate application behavior during network partition affecting {target.name}.",
                    status="requires_review",
                    target=target,
                    fault=fault,
                    duration_seconds=30,
                    blast_radius=get_default_blast_radius("multiple_services", 2),
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
