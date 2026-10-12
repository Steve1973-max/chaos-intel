from abc import ABC, abstractmethod
from .context import ExecutionContext
from .capabilities import AdapterCapabilities
from .result import ExecutionResult
from ..recovery import RecoveryResult

class ExecutionAdapter(ABC):
    """
    Abstract interface for typed execution adapters.
    Must not perform real infrastructure mutations in Step 10B.
    """
    
    @classmethod
    @abstractmethod
    def capabilities(cls) -> AdapterCapabilities:
        raise NotImplementedError
        
    @abstractmethod
    def prepare(self, context: ExecutionContext) -> ExecutionResult:
        raise NotImplementedError
        
    @abstractmethod
    def execute(self, context: ExecutionContext) -> ExecutionResult:
        raise NotImplementedError
        
    @abstractmethod
    def observe(self, context: ExecutionContext) -> ExecutionResult:
        raise NotImplementedError
        
    @abstractmethod
    def abort(self, context: ExecutionContext) -> ExecutionResult:
        raise NotImplementedError
        
    @abstractmethod
    def rollback(self, context: ExecutionContext) -> ExecutionResult:
        raise NotImplementedError
        
    @abstractmethod
    def verify_recovery(self, context: ExecutionContext) -> 'RecoveryResult':
        raise NotImplementedError
        
    @abstractmethod
    def cleanup(self, context: ExecutionContext) -> ExecutionResult:
        raise NotImplementedError
