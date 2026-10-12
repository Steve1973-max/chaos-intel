class ReliabilityError(Exception):
    """Base exception for reliability layer."""
    pass

class LeaseAcquisitionError(ReliabilityError):
    pass

class LeaseOwnershipError(ReliabilityError):
    pass

class IdempotencyConflictError(ReliabilityError):
    pass

class InvalidIdempotencyKeyError(ReliabilityError):
    pass

class OrchestrationTimeoutError(ReliabilityError):
    pass

class OrchestrationCancelledError(ReliabilityError):
    pass

class RecoveryStateUnknownError(ReliabilityError):
    pass
