from typing import List, Dict
from ..models.application import ApplicationModel
from ..models.test_candidate import TestCandidate
from .rules.availability import AvailabilityStrategyRule
from .rules.dependency_resilience import DependencyResilienceStrategyRule
from .rules.external_dependency import ExternalDependencyStrategyRule
from .rules.cyclic_dependency import CyclicDependencyStrategyRule
from .rules.api_resilience import ApiResilienceStrategyRule

def deduplicate_candidates(candidates: List[TestCandidate]) -> List[TestCandidate]:
    deduped = {}
    for c in candidates:
        key = (c.application_id, c.test_type, c.target_id)
        if key not in deduped:
            deduped[key] = c
        else:
            existing_c = deduped[key]
            # Merge evidence
            existing_ev = {f"{e.source}:{e.type}:{e.detail}" for e in existing_c.evidence}
            for ev in c.evidence:
                ev_str = f"{ev.source}:{ev.type}:{ev.detail}"
                if ev_str not in existing_ev:
                    existing_c.evidence.append(ev)
                    existing_ev.add(ev_str)
                    
            # Merge related risk IDs
            for r in c.related_risk_ids:
                if r not in existing_c.related_risk_ids:
                    existing_c.related_risk_ids.append(r)
                    
            # Upgrade priority if necessary
            pri_map = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            if pri_map[c.priority] > pri_map[existing_c.priority]:
                existing_c.priority = c.priority
                
            existing_c.confidence = max(existing_c.confidence, c.confidence)
            
    return list(deduped.values())

def generate_test_candidates(app: ApplicationModel) -> List[TestCandidate]:
    rules = [
        AvailabilityStrategyRule(),
        DependencyResilienceStrategyRule(),
        ExternalDependencyStrategyRule(),
        CyclicDependencyStrategyRule(),
        ApiResilienceStrategyRule()
    ]
    
    all_candidates = []
    for rule in rules:
        cands = rule.generate(app)
        all_candidates.extend(cands)
        
    deduped = deduplicate_candidates(all_candidates)
    
    # Sort for determinism
    sorted_candidates = sorted(deduped, key=lambda c: c.candidate_id)
    return sorted_candidates
