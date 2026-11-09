"""Experiment Specification & Safety Validator for CHAOS-INTEL Phase 3C.

Validates `ExperimentSpecification` against:
1. `FaultCatalog` parameter, method, target-type, and fault-specific max duration rules
2. `BlastRadiusAnalyzer` topological and policy limits
3. Target existence and unambiguous resolution in `ApplicationModel`
4. Approved target environments (`development`, `test`, `staging`)
5. Application Intelligence Safety & Policy Engine (`evaluate_experiment_safety`)
6. Shared JSON Schemas (`experiment.schema.json`, `safety-decision.schema.json`)
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import jsonschema
from pydantic import BaseModel, Field

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.models.application import ApplicationModel
from src.models.experiment import ExperimentSpecification
from src.models.safety import SafetyCheck, SafetyDecision
from src.safety.engine import evaluate_experiment_safety
from src.safety.policy import PolicyConstants

from blast_radius import BlastRadiusAnalyzer, BlastRadiusAssessment
from fault_catalog import FaultCatalog, FaultCatalogError, FaultDefinition


class ExperimentValidationError(ValueError):
    """Raised when an ExperimentSpecification fails validation."""


class ValidationReport(BaseModel):
    """Comprehensive validation report for a chaos experiment."""

    experiment_id: str
    application_id: str
    valid: bool
    fault_definition: Optional[FaultDefinition] = None
    blast_radius_assessment: BlastRadiusAssessment
    safety_decision: SafetyDecision
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ExperimentValidator:
    """Validates chaos experiment specifications and evaluates safety policies."""

    APPROVED_EXECUTION_ENVIRONMENTS: Set[str] = {"development", "test", "staging"}

    def __init__(
        self,
        fault_catalog: Optional[FaultCatalog] = None,
        blast_radius_analyzer: Optional[BlastRadiusAnalyzer] = None,
        allowed_environments: Optional[Set[str]] = None,
    ) -> None:
        self.fault_catalog = fault_catalog or FaultCatalog()
        self.blast_radius_analyzer = blast_radius_analyzer or BlastRadiusAnalyzer()
        self.allowed_environments: Set[str] = (
            set(allowed_environments)
            if allowed_environments is not None
            else set(self.APPROVED_EXECUTION_ENVIRONMENTS)
        )
        self._schemas_dir = Path(__file__).resolve().parents[2] / "packages" / "schemas"

    def _validate_json_schema(self, payload: Dict[str, Any], schema_filename: str) -> List[str]:
        schema_path = self._schemas_dir / schema_filename
        if not schema_path.exists():
            return []
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        validator = jsonschema.Draft7Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        return [
            f"Schema '{schema_filename}' error at '{'.'.join(str(p) for p in err.path) or '<root>'}': {err.message}"
            for err in errors
        ]

    @staticmethod
    def _check_target_in_application(spec: ExperimentSpecification, app: ApplicationModel) -> List[str]:
        errors: List[str] = []
        if not spec.target or not spec.target.id or not spec.target.type:
            return ["Target ID and type are required."]
        if spec.target.type == "unknown":
            return ["Target type 'unknown' is not permitted."]

        matched_ids: Set[str] = set()
        target_id = spec.target.id

        for srv in app.services or []:
            if srv.service_id == target_id or srv.name == target_id:
                matched_ids.add(f"service:{srv.service_id}")
        for dep in app.dependencies or []:
            if dep.name == target_id or dep.target_service_id == target_id:
                matched_ids.add(f"dep:{dep.name}")
        for api in app.apis or []:
            if api.api_id == target_id or api.path == target_id:
                matched_ids.add(f"api:{api.api_id}")
        if app.architecture and app.architecture.nodes:
            for node in app.architecture.nodes:
                if node.node_id == target_id or node.name == target_id:
                    matched_ids.add(f"node:{node.node_id}")

        if len(matched_ids) == 0:
            errors.append(f"Target '{target_id}' (type='{spec.target.type}') does not exist in application '{app.application_id}'.")
        return errors

    def validate(
        self,
        spec: ExperimentSpecification,
        app: ApplicationModel,
        *,
        raise_on_error: bool = False,
    ) -> ValidationReport:
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Application ID consistency
        if spec.application_id != app.application_id:
            errors.append(
                f"Experiment application_id '{spec.application_id}' does not match ApplicationModel '{app.application_id}'."
            )

        # 2. Fault Catalog validation (type, method, parameters, target scope, duration)
        fault_def: Optional[FaultDefinition] = None
        if not spec.fault or not spec.fault.type:
            errors.append("Experiment fault specification is missing.")
        else:
            try:
                fault_def = self.fault_catalog.resolve(spec.fault.type)
                _, param_errors = self.fault_catalog.validate_parameters(
                    fault_def.fault_type, spec.fault.parameters
                )
                errors.extend(param_errors)

                if spec.fault.method not in fault_def.supported_methods:
                    errors.append(
                        f"Fault method '{spec.fault.method}' is not supported for fault '{fault_def.fault_type}'. "
                        f"Supported methods: {fault_def.supported_methods}."
                    )

                if spec.target.type not in fault_def.target_scope.allowed_target_types:
                    errors.append(
                        f"Target type '{spec.target.type}' is not valid for fault '{fault_def.fault_type}'. "
                        f"Allowed target types: {fault_def.target_scope.allowed_target_types}."
                    )

                if spec.blast_radius.scope not in fault_def.target_scope.allowed_blast_scopes:
                    errors.append(
                        f"Blast radius scope '{spec.blast_radius.scope}' is not valid for fault '{fault_def.fault_type}'. "
                        f"Allowed scopes: {fault_def.target_scope.allowed_blast_scopes}."
                    )

                if spec.duration_seconds > fault_def.max_duration_seconds:
                    errors.append(
                        f"Experiment duration ({spec.duration_seconds}s) exceeds fault catalog maximum "
                        f"({fault_def.max_duration_seconds}s) for '{fault_def.fault_type}'."
                    )
            except FaultCatalogError as exc:
                errors.append(str(exc))

        # 3. Global duration ceiling
        if spec.duration_seconds is None or spec.duration_seconds <= 0:
            errors.append(f"Duration ({spec.duration_seconds}) must be a positive integer.")
        elif spec.duration_seconds > PolicyConstants.MAX_DURATION_SECONDS:
            errors.append(
                f"Duration ({spec.duration_seconds}s) exceeds global policy limit ({PolicyConstants.MAX_DURATION_SECONDS}s)."
            )

        # 4. Target existence in ApplicationModel
        errors.extend(self._check_target_in_application(spec, app))

        # 5. Approved environment enforcement
        env = spec.safety.environment_required
        if env == "production" or spec.safety.production_allowed:
            errors.append("Production chaos experiments are blocked by safety policy.")
        elif env is None or env == "unknown":
            errors.append("Target environment is unknown; experiments are restricted to approved environments.")
        elif env not in self.allowed_environments:
            errors.append(
                f"Target environment '{env}' is not in approved environments {sorted(self.allowed_environments)}."
            )

        # 5b. Rollback verification is mandatory for every chaos experiment
        if not spec.safety.rollback_required:
            errors.append("Chaos experiments must set safety.rollback_required=True; rollback must be verified.")
        if not spec.safety.reversible:
            errors.append("Chaos experiments must be reversible.")
        if not spec.abort_conditions:
            errors.append("Chaos experiments must define at least one abort condition.")

        # 6. Blast-radius assessment
        blast_assessment = self.blast_radius_analyzer.assess(spec, app, enforce=False)
        if not blast_assessment.within_limits:
            errors.extend(blast_assessment.violations)

        # 7. Evaluate Safety & Policy Engine (never bypassed)
        spec_for_policy = spec.model_copy(deep=True)
        if fault_def is not None:
            spec_for_policy.fault.type = fault_def.policy_fault_type

        safety_decision = evaluate_experiment_safety(app.application_id, spec_for_policy)

        # Merge any validator/catalog/target/blast-radius errors into the SafetyDecision
        for err_msg in errors:
            if err_msg not in safety_decision.blockers:
                safety_decision.blockers.append(err_msg)
                safety_decision.checks.append(
                    SafetyCheck(
                        check_id=f"chk-{uuid.uuid4().hex[:8]}",
                        category="chaos_validator",
                        status="fail",
                        severity="high",
                        message=err_msg,
                    )
                )

        if len(safety_decision.blockers) > 0:
            safety_decision.decision = "blocked"
            safety_decision.allowed = False
            for blocker in safety_decision.blockers:
                if blocker not in errors:
                    errors.append(blocker)
        elif safety_decision.decision == "requires_configuration":
            for cond in safety_decision.required_conditions:
                warnings.append(cond)

        warnings.extend(safety_decision.warnings)

        # 8. Validate against shared JSON schemas
        errors.extend(self._validate_json_schema(spec.model_dump(mode="json"), "experiment.schema.json"))
        errors.extend(
            self._validate_json_schema(safety_decision.model_dump(mode="json"), "safety-decision.schema.json")
        )

        is_valid = len(errors) == 0 and safety_decision.decision != "blocked"

        report = ValidationReport(
            experiment_id=spec.experiment_id,
            application_id=app.application_id,
            valid=is_valid,
            fault_definition=fault_def,
            blast_radius_assessment=blast_assessment,
            safety_decision=safety_decision,
            errors=errors,
            warnings=warnings,
        )

        if raise_on_error and not is_valid:
            raise ExperimentValidationError("; ".join(errors or ["Experiment blocked by Safety & Policy Engine."]))

        return report

