from abc import ABC, abstractmethod
from typing import List
from ..models.experiment import ExperimentSpecification
from ..models.safety import SafetyCheck

class SafetyRule(ABC):
    @property
    @abstractmethod
    def category(self) -> str:
        pass

    @abstractmethod
    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        """Evaluate an experiment and return one or more safety checks."""
        pass
