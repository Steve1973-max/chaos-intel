import hashlib
from typing import List
from abc import ABC, abstractmethod
from ..models.application import ApplicationModel
from ..models.test_candidate import TestCandidate

class StrategyRule(ABC):
    @property
    @abstractmethod
    def rule_id(self) -> str:
        pass

    @abstractmethod
    def generate(self, app: ApplicationModel) -> List[TestCandidate]:
        """Generate test candidates from the application model and risks."""
        pass
        
    def generate_candidate_id(self, application_id: str, test_type: str, target_id: str) -> str:
        hash_obj = hashlib.md5(f"{application_id}:{self.rule_id}:{test_type}:{target_id}".encode('utf-8'))
        return f"cand-{hash_obj.hexdigest()[:8]}"
