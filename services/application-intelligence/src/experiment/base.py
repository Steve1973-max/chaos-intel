import hashlib
from typing import List, Optional
from abc import ABC, abstractmethod
from ..models.application import ApplicationModel
from ..models.experiment import ExperimentSpecification

class ExperimentRule(ABC):
    @property
    @abstractmethod
    def rule_id(self) -> str:
        pass

    @abstractmethod
    def generate(self, app: ApplicationModel) -> List[ExperimentSpecification]:
        """Generate experiment specifications from the application model and test candidates."""
        pass
        
    def generate_experiment_id(self, application_id: str, fault_type: str, target_id: str) -> str:
        hash_obj = hashlib.md5(f"{application_id}:{self.rule_id}:{fault_type}:{target_id}".encode('utf-8'))
        return f"exp-{hash_obj.hexdigest()[:8]}"
