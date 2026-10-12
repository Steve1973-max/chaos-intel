class OrchestrationError(Exception):
    """Base error for orchestration."""
    pass
    
class InvalidInputError(OrchestrationError):
    pass
    
class IDMismatchError(OrchestrationError):
    pass
    
class OrchestrationRejection(OrchestrationError):
    pass
