import re

def rewrite_orchestrator(path):
    with open(path, "r") as f:
        content = f.read()

    # 1. Update __init__
    init_old = """    def __init__(
        self, 
        registry=None,
        lease_manager: Optional[LeaseManager] = None,
        idempotency_manager: Optional[IdempotencyManager] = None,
        audit_logger: Optional[AuditLogger] = None,
        run_repository=None,
        audit_repository=None,
        transaction_boundary=None
    ):"""
    init_new = """    def __init__(
        self, 
        registry=None,
        lease_manager: Optional[LeaseManager] = None,
        idempotency_manager: Optional[IdempotencyManager] = None,
        audit_logger: Optional[AuditLogger] = None,
        run_repository=None,
        audit_repository=None,
        transaction_boundary=None,
        idempotency_repository=None
    ):"""
    content = content.replace(init_old, init_new)

    content = content.replace("self.cancellation_manager = CancellationManager()", 
                              "self.cancellation_manager = CancellationManager()\n        self.idempotency_repository = idempotency_repository")

    # 2. Update idempotency check in orchestrate
    idempotency_check_old = """        # Phase A2: Idempotency Check
        if idempotency_key:
            fingerprint = self.idempotency_manager.compute_fingerprint({
                "app_id": app.application_id,
                "spec_id": spec.experiment_id,
                "decision_id": decision.decision_id,
                "mode": request.mode
            })
            try:
                is_duplicate, stored_result = self.idempotency_manager.record_request(idempotency_key, fingerprint)
                if is_duplicate:
                    if stored_result:
                        return stored_result
                    else:
                        return self._fail(request, "rejected", ["Concurrent duplicate request is already in progress."])
            except (IdempotencyConflictError, InvalidIdempotencyKeyError) as e:
                return self._fail(request, "rejected", [str(e)])"""

    idempotency_check_new = """        # Phase A2: Idempotency Check
        idempotency_owner = None
        if idempotency_key:
            import uuid
            idempotency_owner = str(uuid.uuid4())
            fingerprint = self.idempotency_manager.compute_fingerprint({
                "app_id": app.application_id,
                "spec_id": spec.experiment_id,
                "decision_id": decision.decision_id,
                "mode": request.mode
            })
            try:
                if self.idempotency_repository:
                    status, stored_result = self.idempotency_repository.reserve(
                        application_id=app.application_id,
                        experiment_id=spec.experiment_id,
                        key=idempotency_key,
                        fingerprint=fingerprint,
                        owner=idempotency_owner
                    )
                    if status == "in_progress":
                        return self._fail(request, "rejected", ["Concurrent duplicate request is already in progress."])
                    elif status == "completed":
                        if stored_result:
                            try:
                                return OrchestrationResponse.model_validate(stored_result)
                            except Exception as e:
                                return self._fail(request, "failed", ["Stored response is malformed or incompatible."])
                        else:
                            return self._fail(request, "failed", ["Stored response is missing."])
                else:
                    is_duplicate, stored_result = self.idempotency_manager.record_request(idempotency_key, fingerprint)
                    if is_duplicate:
                        if stored_result:
                            return stored_result
                        else:
                            return self._fail(request, "rejected", ["Concurrent duplicate request is already in progress."])
            except (IdempotencyConflictError, InvalidIdempotencyKeyError) as e:
                return self._fail(request, "rejected", [str(e)])"""
    content = content.replace(idempotency_check_old, idempotency_check_new)

    # 3. Pass idempotency_owner to _do_orchestrate
    content = content.replace("return self._do_orchestrate(request, request.experiment_run, spec, decision, app, timeout_mgr, idempotency_key)", 
                              "return self._do_orchestrate(request, request.experiment_run, spec, decision, app, timeout_mgr, idempotency_key, idempotency_owner)")
    content = content.replace("def _do_orchestrate(\n        self, request: OrchestrationRequest, initial_run, spec, decision, app, timeout_mgr, idempotency_key\n    ) -> OrchestrationResponse:",
                              "def _do_orchestrate(\n        self, request: OrchestrationRequest, initial_run, spec, decision, app, timeout_mgr, idempotency_key, idempotency_owner=None\n    ) -> OrchestrationResponse:")
    
    # 4. Update store_result at the end of _do_orchestrate
    store_old = """        if idempotency_key:
            self.idempotency_manager.store_result(idempotency_key, response)"""
    
    store_new = """        if idempotency_key:
            if self.idempotency_repository and idempotency_owner:
                try:
                    self.idempotency_repository.publish_result(
                        application_id=app.application_id,
                        experiment_id=spec.experiment_id,
                        key=idempotency_key,
                        owner=idempotency_owner,
                        result=response.model_dump(mode="json")
                    )
                except Exception as e:
                    return OrchestrationResponse(
                        status="outcome_unknown",
                        run_id=run.run_id,
                        experiment_id=spec.experiment_id,
                        safety_decision_id=decision.decision_id,
                        adapter_id=None,
                        mode=request.mode,
                        errors=["Response generated but could not be durably published.", str(e)]
                    )
            else:
                self.idempotency_manager.store_result(idempotency_key, response)"""
    
    content = content.replace(store_old, store_new)
    
    with open(path, "w") as f:
        f.write(content)

rewrite_orchestrator(r"C:\Users\steve\OneDrive\desktop\Major project\services\application-intelligence\src\execution\orchestrator.py")
