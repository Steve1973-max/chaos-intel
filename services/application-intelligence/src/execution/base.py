from abc import ABC, abstractmethod
from ..models.experiment_run import ExperimentRun
from ..models.experiment import ExperimentSpecification

class ExecutionAdapter(ABC):
    """Abstract interface for future execution adapters (e.g. Pumba, ChaosMesh)."""
    
    @abstractmethod
    def prepare(self, run: ExperimentRun, spec: ExperimentSpecification):
        raise NotImplementedError
        
    @abstractmethod
    def execute(self, run: ExperimentRun, spec: ExperimentSpecification):
        raise NotImplementedError
        
    @abstractmethod
    def observe(self, run: ExperimentRun, spec: ExperimentSpecification):
        raise NotImplementedError
        
    @abstractmethod
    def abort(self, run: ExperimentRun, spec: ExperimentSpecification):
        raise NotImplementedError
        
    @abstractmethod
    def rollback(self, run: ExperimentRun, spec: ExperimentSpecification):
        raise NotImplementedError
        
    @abstractmethod
    def verify_recovery(self, run: ExperimentRun, spec: ExperimentSpecification):
        raise NotImplementedError
