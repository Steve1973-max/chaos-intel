from typing import List
import uuid
from .base import SafetyRule
from ..models.experiment import ExperimentSpecification
from ..models.safety import SafetyCheck
from .policy import PolicyConstants

class EnvironmentRule(SafetyRule):
    @property
    def category(self) -> str:
        return "environment"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        checks = []
        
        # Policy 1: Production Block
        if not experiment.safety.production_allowed:
            if experiment.safety.environment_required == "production":
                checks.append(SafetyCheck(
                    check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                    status="fail", severity="critical", message="Production environment explicitly blocked by policy."
                ))
            
        # Policy 2: Unknown Environment
        if experiment.safety.environment_required is None or experiment.safety.environment_required == "unknown":
            checks.append(SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="requires_configuration", severity="high", message="Environment classification is unknown."
            ))
        elif experiment.safety.environment_required not in PolicyConstants.SUPPORTED_ENVIRONMENTS:
            checks.append(SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="fail", severity="high", message=f"Unsupported environment: {experiment.safety.environment_required}"
            ))
        else:
            checks.append(SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="pass", severity="info", message=f"Environment '{experiment.safety.environment_required}' is supported."
            ))
            
        return checks

class ApprovalRule(SafetyRule):
    @property
    def category(self) -> str:
        return "approval"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        if experiment.safety.requires_approval:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="warning", severity="medium", message="Experiment requires explicit human approval."
            )]
        return []

class BlastRadiusRule(SafetyRule):
    @property
    def category(self) -> str:
        return "blast_radius"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        scope = experiment.blast_radius.scope
        max_affected = experiment.blast_radius.max_affected_components
        
        if scope is None or max_affected is None:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="requires_configuration", severity="high", message="Blast radius is not fully defined."
            )]
            
        allowed = PolicyConstants.BLAST_RADIUS_LIMITS.get(scope, 0)
        
        if max_affected > allowed:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="fail", severity="high", message=f"Max affected components ({max_affected}) exceeds policy limit ({allowed}) for scope {scope}."
            )]
            
        if scope == "unknown":
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="fail", severity="high", message="Unknown blast radius is not allowed."
            )]
            
        return [SafetyCheck(
            check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
            status="pass", severity="info", message="Blast radius is within policy limits."
        )]

class RollbackRule(SafetyRule):
    @property
    def category(self) -> str:
        return "rollback"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        if experiment.safety.rollback_required:
            if not experiment.rollback or not experiment.rollback.strategy:
                return [SafetyCheck(
                    check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                    status="requires_configuration", severity="high", message="Rollback required but strategy is missing."
                )]
            if not experiment.safety.reversible:
                return [SafetyCheck(
                    check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                    status="fail", severity="critical", message="Rollback required but experiment is marked non-reversible."
                )]
            
        return [SafetyCheck(
            check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
            status="pass", severity="info", message="Rollback requirements satisfied."
        )]

class SteadyStateRule(SafetyRule):
    @property
    def category(self) -> str:
        return "steady_state"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        if experiment.steady_state.required:
            if not experiment.steady_state.checks:
                return [SafetyCheck(
                    check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                    status="requires_configuration", severity="high", message="Steady state is required but checks are empty."
                )]
        return [SafetyCheck(
            check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
            status="pass", severity="info", message="Steady state requirements satisfied."
        )]

class AbortConditionsRule(SafetyRule):
    @property
    def category(self) -> str:
        return "abort_conditions"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        if not experiment.abort_conditions:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="requires_configuration", severity="critical", message="Abort conditions missing."
            )]
            
        for ac in experiment.abort_conditions:
            if not ac.metric or not ac.operator:
                return [SafetyCheck(
                    check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                    status="requires_configuration", severity="high", message="Abort condition missing metric or operator."
                )]
            if ac.threshold is None and not ac.requires_configuration:
                return [SafetyCheck(
                    check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                    status="requires_configuration", severity="high", message="Abort condition threshold missing but not marked for config."
                )]
            if ac.action not in ("abort", "rollback"):
                return [SafetyCheck(
                    check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                    status="fail", severity="high", message=f"Unsupported abort action: {ac.action}"
                )]
                
        return [SafetyCheck(
            check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
            status="pass", severity="info", message="Abort conditions satisfied."
        )]

class TargetRule(SafetyRule):
    @property
    def category(self) -> str:
        return "target"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        if not experiment.target or not experiment.target.id:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="requires_configuration", severity="high", message="Target ID missing."
            )]
        if experiment.target.type == "unknown":
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="requires_configuration", severity="high", message="Target type is unknown."
            )]
            
        return [SafetyCheck(
            check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
            status="pass", severity="info", message="Target validation satisfied."
        )]

class FaultRule(SafetyRule):
    @property
    def category(self) -> str:
        return "fault"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        if not experiment.fault or not experiment.fault.type or not experiment.fault.method:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="requires_configuration", severity="high", message="Fault definition missing fields."
            )]
            
        if experiment.fault.type not in PolicyConstants.SUPPORTED_FAULTS:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="fail", severity="high", message=f"Unknown fault type: {experiment.fault.type}"
            )]
            
        return [SafetyCheck(
            check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
            status="pass", severity="info", message="Fault validation satisfied."
        )]

class DurationRule(SafetyRule):
    @property
    def category(self) -> str:
        return "duration"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        if experiment.duration_seconds is None:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="requires_configuration", severity="high", message="Duration is missing."
            )]
        
        if experiment.duration_seconds <= 0:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="fail", severity="high", message="Duration must be > 0."
            )]
            
        if experiment.duration_seconds > PolicyConstants.MAX_DURATION_SECONDS:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="fail", severity="high", message=f"Duration exceeds max allowed limit ({PolicyConstants.MAX_DURATION_SECONDS}s)."
            )]
            
        return [SafetyCheck(
            check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
            status="pass", severity="info", message="Duration is within policy limits."
        )]

class CapabilitiesRule(SafetyRule):
    @property
    def category(self) -> str:
        return "capabilities"

    def evaluate(self, experiment: ExperimentSpecification) -> List[SafetyCheck]:
        req_cap = PolicyConstants.CAPABILITY_MAPPINGS.get(experiment.fault.method)
        if req_cap:
            return [SafetyCheck(
                check_id=f"chk-{uuid.uuid4().hex[:8]}", category=self.category,
                status="requires_configuration", severity="medium", message=f"Requires {req_cap} capability validation in environment."
            )]
            
        return []
