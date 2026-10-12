from typing import Dict, Set
from .states import LifecycleState
from .errors import InvalidStateTransitionError

VALID_TRANSITIONS: Dict[str, Set[str]] = {
    LifecycleState.CREATED: {LifecycleState.PREFLIGHT},
    LifecycleState.PREFLIGHT: {LifecycleState.AUTHORIZATION_PENDING, LifecycleState.FAILED},
    LifecycleState.AUTHORIZATION_PENDING: {LifecycleState.AUTHORIZED, LifecycleState.FAILED},
    LifecycleState.AUTHORIZED: {LifecycleState.SETUP},
    LifecycleState.SETUP: {LifecycleState.RUNNING, LifecycleState.FAILED},
    LifecycleState.RUNNING: {LifecycleState.OBSERVING, LifecycleState.ABORT_REQUESTED, LifecycleState.FAILED},
    LifecycleState.OBSERVING: {LifecycleState.ROLLBACK, LifecycleState.RECOVERY_CHECK, LifecycleState.ABORT_REQUESTED, LifecycleState.FAILED},
    LifecycleState.ABORT_REQUESTED: {LifecycleState.ABORTED, LifecycleState.ROLLBACK},
    LifecycleState.ABORTED: {LifecycleState.ROLLBACK},
    LifecycleState.ROLLBACK: {LifecycleState.RECOVERY_CHECK, LifecycleState.ROLLBACK_FAILED},
    LifecycleState.RECOVERY_CHECK: {LifecycleState.COMPLETED, LifecycleState.RECOVERY_FAILED, LifecycleState.FAILED, LifecycleState.ABORTED},
    LifecycleState.COMPLETED: set(),
    LifecycleState.FAILED: set(),
    LifecycleState.ROLLBACK_FAILED: set(),
    LifecycleState.RECOVERY_FAILED: set()
}

def assert_valid_transition(current_state: str, new_state: str):
    allowed = VALID_TRANSITIONS.get(current_state, set())
    if new_state not in allowed:
        raise InvalidStateTransitionError(f"Invalid transition from {current_state} to {new_state}")
