from typing import List
from ..base import ExperimentRule
from ...models.application import ApplicationModel
from ...models.experiment import ExperimentSpecification, Target, Fault
from ..defaults import get_default_blast_radius, get_default_steady_state, get_default_abort_conditions, get_default_rollback, get_default_safety

class QueueExperimentRule(ExperimentRule):
    @property
    def rule_id(self) -> str:
        return "exp-queue"

    def generate(self, app: ApplicationModel) -> List[ExperimentSpecification]:
        experiments = []
        for cand in app.test_candidates:
            if cand.test_type == "dependency_resilience":
                is_queue = False
                for dep in app.dependencies:
                    if dep.name == cand.target_id and dep.dependency_type in ("message_broker", "kafka", "rabbitmq"):
                        is_queue = True
                
                if not is_queue:
                    continue
                    
                target = Target(type="message_broker", id=cand.target_id, name=cand.target_id)
                fault = Fault(type="queue_backlog", method="message_consumption_delay")
                
                exp = ExperimentSpecification(
                    experiment_id=self.generate_experiment_id(app.application_id, fault.type, target.id),
                    application_id=app.application_id,
                    candidate_ids=[cand.candidate_id],
                    name=f"Queue backlog simulation for {target.name}",
                    hypothesis=f"Experiment designed to evaluate application behavior when messages for {target.name} are delayed causing backlog.",
                    status="draft",
                    target=target,
                    fault=fault,
                    duration_seconds=60,
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
