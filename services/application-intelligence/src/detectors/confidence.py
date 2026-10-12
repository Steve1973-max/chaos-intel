from typing import List
from ..models.technology import Evidence

def calculate_confidence(evidences: List[Evidence]) -> float:
    """
    Calculates a deterministic confidence score based on the provided evidences.
    This is an evidence-strength score, not statistically calibrated.
    """
    if not evidences:
        return 0.0
    
    score = 0.0
    for ev in evidences:
        if ev.type in ("manifest_dependency", "manifest_dev_dependency"):
            score += 0.8
        elif ev.type == "lockfile":
            score += 0.9
        elif ev.type == "configuration":
            score += 0.9
        elif ev.type == "source_import":
            score += 0.7
        elif ev.type == "filename":
            score += 0.5
        elif ev.type == "file_extension":
            score += 0.4
        elif ev.type == "directory_structure":
            score += 0.2
        else:
            score += 0.1
            
    # Cap at 0.99 for maximum certainty
    return min(score, 0.99)
