"""Experiment Registry for CHAOS-INTEL Phase 3C.

Stores and queries validated `ExperimentSpecification`s, `SafetyDecision`s,
`ValidationReport`s, and `ExperimentRun` instances created via the shared
durable lifecycle.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.execution.lifecycle import create_experiment_run
from src.models.application import ApplicationModel
from src.models.experiment import ExperimentSpecification
from src.models.experiment_run import ExperimentRun
from src.models.safety import SafetyDecision

from experiment_validator import ExperimentValidator, ValidationReport


class ExperimentRegistry:
    """In-memory registry of chaos experiments, safety decisions, and runs."""

    def __init__(self, validator: Optional[ExperimentValidator] = None) -> None:
        self.validator = validator or ExperimentValidator()
        self._experiments: Dict[str, ExperimentSpecification] = {}
        self._validation_reports: Dict[str, ValidationReport] = {}
        self._safety_decisions: Dict[str, SafetyDecision] = {}
        self._runs: Dict[str, ExperimentRun] = {}

    def register_experiment(
        self,
        spec: ExperimentSpecification,
        app: ApplicationModel,
        *,
        overwrite: bool = False,
        require_valid: bool = True,
    ) -> ValidationReport:
        if spec.experiment_id in self._experiments and not overwrite:
            raise ValueError(f"Experiment '{spec.experiment_id}' is already registered.")

        report = self.validator.validate(spec, app, raise_on_error=require_valid)
        self._experiments[spec.experiment_id] = spec
        self._validation_reports[spec.experiment_id] = report
        self._safety_decisions[spec.experiment_id] = report.safety_decision
        return report

    def store_validated(self, spec: ExperimentSpecification, report: ValidationReport) -> None:
        """Record a specification and its validation outcome (valid or rejected) for audit/reporting."""
        self._experiments[spec.experiment_id] = spec
        self._validation_reports[spec.experiment_id] = report
        self._safety_decisions[spec.experiment_id] = report.safety_decision

    def find_run(self, run_id: str) -> Optional[ExperimentRun]:
        return self._runs.get(run_id)

    def get_experiment(self, experiment_id: str) -> ExperimentSpecification:
        if experiment_id not in self._experiments:
            raise KeyError(f"Experiment '{experiment_id}' is not registered.")
        return self._experiments[experiment_id]

    def get_validation_report(self, experiment_id: str) -> ValidationReport:
        if experiment_id not in self._validation_reports:
            raise KeyError(f"ValidationReport for experiment '{experiment_id}' is not registered.")
        return self._validation_reports[experiment_id]

    def get_safety_decision(self, experiment_id: str) -> SafetyDecision:
        if experiment_id not in self._safety_decisions:
            raise KeyError(f"SafetyDecision for experiment '{experiment_id}' is not registered.")
        return self._safety_decisions[experiment_id]

    def list_experiments(self, application_id: Optional[str] = None) -> List[ExperimentSpecification]:
        specs = [self._experiments[k] for k in sorted(self._experiments.keys())]
        if application_id is not None:
            specs = [s for s in specs if s.application_id == application_id]
        return specs

    def create_run(
        self,
        experiment_id: str,
        *,
        run_id_override: Optional[str] = None,
    ) -> ExperimentRun:
        spec = self.get_experiment(experiment_id)
        decision = self.get_safety_decision(experiment_id)
        run = create_experiment_run(spec, decision)
        if run_id_override:
            run.run_id = run_id_override
        self._runs[run.run_id] = run
        return run

    def record_run(self, run: ExperimentRun) -> None:
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> ExperimentRun:
        if run_id not in self._runs:
            raise KeyError(f"ExperimentRun '{run_id}' is not registered.")
        return self._runs[run_id]

    def list_runs(self, experiment_id: Optional[str] = None) -> List[ExperimentRun]:
        runs = [self._runs[k] for k in sorted(self._runs.keys())]
        if experiment_id is not None:
            runs = [r for r in runs if r.experiment_id == experiment_id]
        return runs

