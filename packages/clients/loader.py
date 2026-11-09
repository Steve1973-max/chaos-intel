"""Service Module Loader for CHAOS-INTEL.

Provides clean, isolated loading of subsystem classes avoiding namespace collisions
on top-level packages such as 'schemas' and 'adapters'.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Tuple

_ROOT = Path(__file__).resolve().parents[2]
_AI_PATH = _ROOT / "services" / "application-intelligence"
_TA_PATH = _ROOT / "services" / "testing-agents"
_CE_PATH = _ROOT / "services" / "chaos-engine"
_FI_PATH = _ROOT / "services" / "failure-intelligence"


def _cleanup_modules(*prefixes: str) -> None:
    for k in list(sys.modules.keys()):
        for prefix in prefixes:
            if k == prefix or k.startswith(f"{prefix}."):
                sys.modules.pop(k, None)


def get_app_intel_classes() -> Tuple[Any, Any, Any]:
    """Load Application Intelligence models and analysis entrypoint."""
    if str(_AI_PATH) not in sys.path:
        sys.path.insert(0, str(_AI_PATH))
    from src.models.application import ApplicationModel
    from src.models.architecture import ArchitectureGraph
    from src.main import analyze_application
    return ApplicationModel, ArchitectureGraph, analyze_application


def get_testing_agents_classes() -> Tuple[Any, Any, Any]:
    """Load Testing Agents planner, execution engine, and approval model."""
    get_app_intel_classes()
    if str(_TA_PATH) not in sys.path:
        sys.path.insert(0, str(_TA_PATH))
    _cleanup_modules("schemas", "adapters")
    from test_planner import TestPlanner
    from execution.engine import TestExecutionEngine
    from execution.sandbox import ExecutionApproval
    return TestPlanner, TestExecutionEngine, ExecutionApproval


def get_chaos_engine_classes() -> Tuple[Any, Any, Any, Any, Any]:
    """Load Chaos Engine catalog, validator, dry-run adapter, report, and target."""
    get_app_intel_classes()
    if str(_CE_PATH) not in sys.path:
        sys.path.insert(0, str(_CE_PATH))
    _cleanup_modules("schemas", "adapters")
    from fault_catalog import FaultCatalog
    from experiment_validator import ExperimentValidator
    from adapters.dry_run import ChaosDryRunAdapter
    from engine_models import ChaosExperimentReport
    from src.models.experiment import Target
    return FaultCatalog, ExperimentValidator, ChaosDryRunAdapter, ChaosExperimentReport, Target


def get_failure_intel_classes() -> Tuple[Any, Any, Any, Any]:
    """Load Failure Intelligence unified analyzer and schemas."""
    get_app_intel_classes()
    if str(_FI_PATH) not in sys.path:
        sys.path.insert(0, str(_FI_PATH))
    _cleanup_modules("schemas", "adapters")
    from unified_analyzer import UnifiedFailureAnalyzer
    from schemas.telemetry import NormalizedMetricPoint, StructuredLogEntry, TraceSpan
    return UnifiedFailureAnalyzer, NormalizedMetricPoint, StructuredLogEntry, TraceSpan
