import os
import sys
sys.path.append(os.path.abspath('.'))

from src.models.application import ApplicationModel
from src.models.service import Service
from src.models.experiment import ExperimentSpecification, Fault, Target, Safety, BlastRadius, SteadyState, Rollback
from src.models.safety import SafetyDecision
from src.execution.lifecycle import create_experiment_run
from src.execution.orchestration_models import OrchestrationRequest
from src.execution.orchestrator import OrchestrationController

app = ApplicationModel(
    application_id="app-1",
    name="test-app",
    technologies=[],
    services=[Service(service_id="svc-1", name="service-1", type="backend", source_path="/", application_id="app-1")],
    dependencies=[],
    apis=[],
    architecture={"nodes": [], "edges": []}
)

spec = ExperimentSpecification(
    experiment_id="exp-1",
    application_id="app-1",
    candidate_ids=[],
    name="test-exp",
    hypothesis="test",
    status="draft",
    fault=Fault(type="availability", method="kill", parameters={}),
    target=Target(type="service", id="svc-1", name="service-1"),
    duration_seconds=60,
    blast_radius=BlastRadius(scope="service", max_affected_components=1),
    steady_state=SteadyState(required=False),
    rollback=Rollback(strategy="none", automatic=False),
    safety=Safety(requires_approval=True, rollback_required=True)
)

decision = SafetyDecision(
    decision_id="dec-1",
    experiment_id="exp-1",
    application_id="app-1",
    decision="approved",
    allowed=True,
    reason="looks good",
    blockers=[],
    required_approvals=[],
    required_conditions=[]
)

run = create_experiment_run(spec, decision)

req = OrchestrationRequest(
    application_model=app,
    experiment_specification=spec,
    safety_decision=decision,
    experiment_run=run,
    mode="dry_run"
)

ctrl = OrchestrationController()
resp = ctrl.orchestrate(req)
print("STATUS:", resp.status)
print("ERRORS:", resp.errors)
