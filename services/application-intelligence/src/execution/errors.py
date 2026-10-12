class LifecycleError(Exception):
    """Base class for all execution lifecycle errors."""
    pass

class InvalidStateTransitionError(LifecycleError):
    pass

class SafetyGateError(LifecycleError):
    pass

class ApprovalRequiredError(LifecycleError):
    pass

class ConfigurationRequiredError(LifecycleError):
    pass

class PreflightError(LifecycleError):
    pass

class ExperimentMismatchError(LifecycleError):
    pass

class AuthorizationError(LifecycleError):
    pass

class RollbackError(LifecycleError):
    pass

class RecoveryError(LifecycleError):
    pass
