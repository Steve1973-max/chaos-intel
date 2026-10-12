from typing import List
from ..models.application import ApplicationModel
from ..models.experiment import ExperimentSpecification
from .rules.availability import AvailabilityExperimentRule
from .rules.dependency import DependencyExperimentRule
from .rules.external_dependency import ExternalDependencyExperimentRule
from .rules.latency import LatencyExperimentRule
from .rules.network import NetworkExperimentRule
from .rules.queue import QueueExperimentRule

def deduplicate_experiments(experiments: List[ExperimentSpecification]) -> List[ExperimentSpecification]:
    deduped = {}
    for exp in experiments:
        key = (exp.application_id, exp.fault.type, exp.target.id)
        if key not in deduped:
            deduped[key] = exp
        else:
            existing = deduped[key]
            
            # Merge candidate IDs
            for c in exp.candidate_ids:
                if c not in existing.candidate_ids:
                    existing.candidate_ids.append(c)
                    
            # Merge evidence
            existing_ev = {f"{e.source}:{e.type}:{e.detail}" for e in existing.evidence}
            for ev in exp.evidence:
                ev_str = f"{ev.source}:{ev.type}:{ev.detail}"
                if ev_str not in existing_ev:
                    existing.evidence.append(ev)
                    existing_ev.add(ev_str)
                    
            # Highest confidence
            existing.confidence = max(existing.confidence, exp.confidence)
            
    return list(deduped.values())

def generate_experiment_specifications(app: ApplicationModel) -> List[ExperimentSpecification]:
    rules = [
        AvailabilityExperimentRule(),
        DependencyExperimentRule(),
        ExternalDependencyExperimentRule(),
        LatencyExperimentRule(),
        NetworkExperimentRule(),
        QueueExperimentRule()
    ]
    
    all_experiments = []
    for rule in rules:
        all_experiments.extend(rule.generate(app))
        
    deduped = deduplicate_experiments(all_experiments)
    
    return sorted(deduped, key=lambda e: e.experiment_id)
