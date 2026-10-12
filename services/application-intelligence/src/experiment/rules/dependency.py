from typing import List
from ..base import ExperimentRule
from ...models.application import ApplicationModel
from ...models.experiment import ExperimentSpecification, Target, Fault
from ..defaults import get_default_blast_radius, get_default_steady_state, get_default_abort_conditions, get_default_rollback, get_default_safety

class DependencyExperimentRule(ExperimentRule):
    @property
    def rule_id(self) -> str:
        return "exp-dep"

    def generate(self, app: ApplicationModel) -> List[ExperimentSpecification]:
        experiments = []
        for cand in app.test_candidates:
            if cand.test_type == "dependency_resilience":
                # Find if it's external or queue
                is_external = False
                is_queue = False
                
                for dep in app.dependencies:
                    if dep.name == cand.target_id:
                        if dep.dependency_type == "external_api":
                            is_external = True
                        elif dep.dependency_type in ("message_broker", "kafka", "rabbitmq"):
                            is_queue = True
                
                # Handled by other rules
                if is_external or is_queue:
                    continue
                    
                status = "draft" if cand.target_id else "requires_review"
                
                t_type = "dependency"
                target = Target(type=t_type, id=cand.target_id, name=cand.target_id)
                fault = Fault(type="dependency_unavailable", method="dependency_stop")
                
                exp = ExperimentSpecification(
                    experiment_id=self.generate_experiment_id(app.application_id, fault.type, target.id),
                    application_id=app.application_id,
                    candidate_ids=[cand.candidate_id],
                    name=f"Validate resilience to {target.name} failure",
                    hypothesis=f"Experiment designed to evaluate application behavior when the database or dependency {target.name} becomes unavailable.",
                    status=status,
                    target=target,
                    fault=fault,
                    duration_seconds=30,
                    blast_radius=get_default_blast_radius("single_dependency", 1),
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
