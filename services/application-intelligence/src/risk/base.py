import hashlib
from typing import List
from abc import ABC, abstractmethod
from ..models.application import ApplicationModel
from ..models.risk import RiskFinding

class RiskRule(ABC):
    @property
    @abstractmethod
    def rule_id(self) -> str:
        pass

    @property
    @abstractmethod
    def category(self) -> str:
        pass
        
    @property
    @abstractmethod
    def risk_type(self) -> str:
        pass

    @abstractmethod
    def evaluate(self, app: ApplicationModel) -> List[RiskFinding]:
        """Evaluate the rule against the application model and return findings."""
        pass
        
    def generate_risk_id(self, application_id: str, target_id: str) -> str:
        hash_obj = hashlib.md5(f"{application_id}:{self.risk_type}:{target_id}".encode('utf-8'))
        return f"risk-{hash_obj.hexdigest()[:8]}"
