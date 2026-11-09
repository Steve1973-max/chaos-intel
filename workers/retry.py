"""Retry classification and failure semantics for distributed workers."""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Dict, Optional


class RetryClassification(str, Enum):
    """Classification of errors determining retry and replay safety."""

    TRANSIENT = "transient"
    # Safe to retry with exponential backoff (e.g., temporary lock contention, network blip on idempotent GET).

    DETERMINISTIC = "deterministic"
    # Never retry; repeating will produce the identical failure (e.g., validation error, bad payload, missing file).

    UNCERTAIN = "uncertain"
    # UNCERTAIN OUTCOME: Network timeout during mutating operation, post-commit drop.
    # INVARIANT: MUST NEVER be automatically replayed! Requires human intervention or manual reconciliation.


class ClassifiedError(Exception):
    """Exception wrapping classification metadata."""

    def __init__(
        self,
        message: str,
        classification: RetryClassification,
        original_exception: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.classification = classification
        self.original_exception = original_exception
        self.details = details or {}


def classify_error(exc: Exception, is_mutation: bool = False) -> RetryClassification:
    """Determine retry classification for an encountered exception."""
    if isinstance(exc, ClassifiedError):
        return exc.classification

    err_str = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    # If the operation was a mutation and timed out or disconnected, it is strictly UNCERTAIN
    if is_mutation:
        if any(k in err_str or k in exc_type for k in ("timeout", "timedout", "connectionreset", "econnreset", "brokenpipe")):
            return RetryClassification.UNCERTAIN

    # Known transient errors
    if any(k in err_str or k in exc_type for k in ("deadlock", "locknotavailable", "connpool", "connectionrefused", "temporarily unavailable")):
        return RetryClassification.TRANSIENT

    # Timeout on non-mutating / read-only calls
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) and not is_mutation:
        return RetryClassification.TRANSIENT

    # Validation and client errors are deterministic
    if any(k in err_str or k in exc_type for k in ("validationerror", "valueerror", "filenotfound", "keyerror", "typeerror", "notfound", "unauthorized", "forbidden")):
        return RetryClassification.DETERMINISTIC

    # Default fallback: If uncertain whether side-effects occurred on mutation, treat as UNCERTAIN
    if is_mutation:
        return RetryClassification.UNCERTAIN

    return RetryClassification.DETERMINISTIC

