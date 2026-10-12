from typing import List
from ..base import ExperimentRule
from ...models.application import ApplicationModel
from ...models.experiment import ExperimentSpecification, Target, Fault
from ..defaults import get_default_blast_radius, get_default_steady_state, get_default_abort_conditions, get_default_rollback, get_default_safety

class ExternalDependencyExperimentRule(ExperimentRule):
    @property
    def rule_id(self) -> str:
        return "exp-ext-dep"

    def generate(self, app: ApplicationModel) -> List[ExperimentSpecification]:
        experiments = []
        for cand in app.test_candidates:
            if cand.test_type == "dependency_resilience":
                is_external = False
                for dep in app.dependencies:
                    if dep.name == cand.target_id and dep.dependency_type == "external_api":
                        is_external = True
                
                if not is_external:
                    continue
                    
                target = Target(type="external_service", id=cand.target_id, name=cand.target_id)
                
                fault_type = "dependency_unavailable"
                method = "external_dependency_unavailable"
                if "latency" in cand.expected_failure_mode or "slow" in cand.hypothesis:
                    fault_type = "dependency_slow"
                
                fault = Fault(type=fault_type, method=method)
                
                exp = ExperimentSpecification(
                    experiment_id=self.generate_experiment_id(app.application_id, fault.type, target.id),
                    application_id=app.application_id,
                    candidate_ids=[cand.candidate_id],
                    name=f"Validate resilience to external API {target.name}",
                    hypothesis=f"Experiment designed to evaluate application behavior when the external API {target.name} becomes unavailable or slow.",
                    status="draft",
                    target=target,
                    fault=fault,
                    duration_seconds=30,
                    blast_radius=get_default_blast_radius("single_external_dependency", 1),
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
