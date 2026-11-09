"""Task Registry mapping background task names to executable async handlers."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

TaskHandler = Callable[[Dict[str, Any], str, Any], Awaitable[Dict[str, Any]]]


class TaskRegistry:
    """Registry for async task handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, TaskHandler] = {}

    def register(self, task_name: str) -> Callable[[TaskHandler], TaskHandler]:
        """Decorator to register a task handler."""

        def decorator(handler: TaskHandler) -> TaskHandler:
            if task_name in self._handlers:
                logger.warning(f"Overwriting existing handler for task '{task_name}'")
            self._handlers[task_name] = handler
            return handler

        return decorator

    def get_handler(self, task_name: str) -> Optional[TaskHandler]:
        """Retrieve handler for task name."""
        return self._handlers.get(task_name)

    def has_task(self, task_name: str) -> bool:
        """Check whether task is registered."""
        return task_name in self._handlers

    def list_tasks(self) -> list[str]:
        """List registered task names."""
        return sorted(self._handlers.keys())


# Global default registry
default_task_registry = TaskRegistry()

