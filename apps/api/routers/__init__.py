"""API Routers package."""

from .applications import router as applications_router
from .testing import router as testing_router
from .chaos import router as chaos_router
from .telemetry import router as telemetry_router
from .intelligence import router as intelligence_router
from .orchestration import router as orchestration_router
from .health import router as health_router

__all__ = [
    "applications_router",
    "testing_router",
    "chaos_router",
    "telemetry_router",
    "intelligence_router",
    "orchestration_router",
    "health_router",
]

