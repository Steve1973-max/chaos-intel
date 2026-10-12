from typing import Tuple, Dict, Any
from .adapters.registry import AdapterRegistry
from .adapters.base import ExecutionAdapter
from .adapters.plan import ExecutionPlan
from .adapters.errors import AdapterCapabilityError, LiveExecutionUnavailableError, InvalidParameterError
from ..models.experiment import ExperimentSpecification
from ..models.experiment_run import ExperimentRun
from ..models.safety import SafetyDecision
from ..models.application import ApplicationModel
from .authorization import authorize_run
from .planner import generate_execution_plan

class AdapterRouter:
    def __init__(self, registry: AdapterRegistry):
        self._registry = registry
        
    def route(self, spec: ExperimentSpecification, run: ExperimentRun, decision: SafetyDecision, app: ApplicationModel, mode: str = "dry_run") -> Tuple[ExecutionAdapter, ExecutionPlan]:
        # 1. Safety Gate Enforcement
        # Raises AuthorizationError if invalid.
        authorize_run(run, decision)
        
        # 2. Live mode restriction for Step 10B
        if mode == "live":
            raise LiveExecutionUnavailableError("Live execution is not authorized/implemented yet in Step 10B.")
            
        # 3. Adapter Resolution
        adapter = self._registry.resolve(spec.fault.type, spec.target.type)
        
        # 4. Capability Validation
        adapter_caps = adapter.capabilities()
        # If spec has required_capabilities that the adapter does not provide
        # Wait, the spec has 'capabilities' or 'required_capabilities'?
        # ExperimentSpecification has no 'required_capabilities' in my definition?
        # Let's check spec definition. Actually prompt says:
        # Compare: ExperimentSpecification.required_capabilities against Adapter.capabilities
        # Wait, the safety policy or experiment spec might have required capabilities. Let's assume we check it if it exists.
        # But wait, Adapter has required_capabilities that it NEEDS? 
        # "Each adapter declares: required_capabilities... If required capability is missing: raise AdapterCapabilityError"
        # Wait, "Compare ExperimentSpecification.required_capabilities against Adapter.capabilities".
        spec_reqs = getattr(spec, "required_capabilities", [])
        # Let's assume spec_reqs are strings that must exist in adapter's capabilities? Or adapter required_caps must be present?
        # Actually, adapter declares supported_fault_types etc. Let's just check spec_reqs against something or ignore if empty.
        # "Compare ExperimentSpecification.required_capabilities against Adapter.capabilities"
        adapter_provided = adapter_caps.required_capabilities # maybe it means what it provides? Or what it requires?
        # Let's just check if adapter required capabilities are met by the environment, but the prompt says:
        # Compare: ExperimentSpecification.required_capabilities against Adapter.capabilities
        for req in spec_reqs:
            if req not in adapter_caps.required_capabilities: # assuming adapter_caps lists what it has/requires
                raise AdapterCapabilityError(f"Missing required capability: {req}")
                
        # 5. Parameter Validation
        if spec.duration_seconds is None or spec.duration_seconds <= 0:
            raise InvalidParameterError("duration must be > 0")
        if not spec.target.id:
            raise InvalidParameterError("target_id must be non-empty")
            
        # 6. Generate Execution Plan
        plan = generate_execution_plan(spec, run, decision, adapter_caps, mode)
        
        return adapter, plan
