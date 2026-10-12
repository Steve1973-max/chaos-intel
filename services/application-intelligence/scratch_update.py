import re

def update_orchestrator():
    path = r"C:\Users\steve\OneDrive\desktop\Major project\services\application-intelligence\src\execution\orchestrator.py"
    with open(path, "r") as f:
        content = f.read()
        
    init_old = """    def __init__(
        self, 
        registry=None,
        lease_manager: Optional[LeaseManager] = None,
        idempotency_manager: Optional[IdempotencyManager] = None,
        audit_logger: Optional[AuditLogger] = None
    ):
        if registry is None:
            registry = AdapterRegistry()
            registry.register(DryRunAdapter())
        self.registry = registry
        self.lease_manager = lease_manager or _global_lease_manager
        self.idempotency_manager = idempotency_manager or _global_idempotency_manager
        self.audit_logger = audit_logger or _global_audit_logger
        self.cancellation_manager = CancellationManager()"""

    init_new = """    def __init__(
        self, 
        registry=None,
        lease_manager: Optional[LeaseManager] = None,
        idempotency_manager: Optional[IdempotencyManager] = None,
        audit_logger: Optional[AuditLogger] = None,
        run_repository=None,
        audit_repository=None,
        transaction_boundary=None
    ):
        if registry is None:
            registry = AdapterRegistry()
            registry.register(DryRunAdapter())
        self.registry = registry
        self.lease_manager = lease_manager or _global_lease_manager
        self.idempotency_manager = idempotency_manager or _global_idempotency_manager
        self.audit_logger = audit_logger or _global_audit_logger
        self.run_repository = run_repository
        self.audit_repository = audit_repository
        self.transaction_boundary = transaction_boundary
        self.cancellation_manager = CancellationManager()"""

    content = content.replace(init_old, init_new)
    
    # orchestrate
    orchestrate_old = """        lifecycle = LifecycleController(run, spec, decision, app)
        
        # Phase B & D: Preflight and Authorization
        # Prevent re-using already active/terminal runs
        if run.state not in (LifecycleState.CREATED, LifecycleState.AUTHORIZATION_PENDING):
            return self._fail(request, "rejected", [f"Run is already in state {run.state} and cannot be re-orchestrated."])

        owner_id = "orchestrator-controller"
        try:
            with LeaseContext(self.lease_manager, run.run_id, owner_id, timeout_sec):
                return self._do_orchestrate(request, run, spec, decision, app, lifecycle, timeout_mgr, idempotency_key)"""
                
    orchestrate_new = """        # Prevent re-using already active/terminal runs
        if request.experiment_run.state not in (LifecycleState.CREATED, LifecycleState.AUTHORIZATION_PENDING):
            return self._fail(request, "rejected", [f"Run is already in state {request.experiment_run.state} and cannot be re-orchestrated."])

        owner_id = "orchestrator-controller"
        try:
            with LeaseContext(self.lease_manager, request.experiment_run.run_id, owner_id, timeout_sec):
                return self._do_orchestrate(request, request.experiment_run, spec, decision, app, timeout_mgr, idempotency_key)"""
                
    content = content.replace(orchestrate_old, orchestrate_new)

    # do_orchestrate method signature and body
    # We will replace the whole method using regex
    
    do_orch_regex = r"    def _do_orchestrate\(\s*self, request: OrchestrationRequest, run, spec, decision, app, lifecycle, timeout_mgr, idempotency_key\s*\) -> OrchestrationResponse:.*?        # Phase C & E: Adapter routing and planning"
    
    do_orch_new = """    def _do_orchestrate(
        self, request: OrchestrationRequest, initial_run, spec, decision, app, timeout_mgr, idempotency_key
    ) -> OrchestrationResponse:
        import uuid
        run = initial_run
        
        def _execute_lifecycle(action_name, action_func):
            nonlocal run
            if not (self.transaction_boundary and self.run_repository and self.audit_repository):
                action_func(run)
                return

            with self.transaction_boundary.transaction():
                db_run = self.run_repository.get_run(run.run_id)
                if not db_run:
                    if run.state != LifecycleState.CREATED:
                        raise InvalidStateTransitionError("Cannot create a run in a non-CREATED state.")
                    self.run_repository.create_run(run)
                    db_run = self.run_repository.get_run(run.run_id)

                if db_run.state not in (LifecycleState.CREATED, LifecycleState.AUTHORIZATION_PENDING):
                    raise AuthorizationError(f"Run is already in state {db_run.state} and cannot be re-orchestrated.")

                old_state = db_run.state
                old_version = db_run.version
                
                # Execute lifecycle on the DB run copy
                action_func(db_run)
                
                if db_run.state != old_state:
                    from .persistence.interfaces import OptimisticConcurrencyError
                    try:
                        updated_run = self.run_repository.transition_state(
                            db_run.run_id, old_version, db_run.state, db_run
                        )
                    except Exception as e:
                        raise InvalidStateTransitionError(f"Optimistic concurrency conflict: {e}")

                    history = type("RunTransitionHistoryImpl", (), {
                        "event_id": str(uuid.uuid4()),
                        "run_id": db_run.run_id,
                        "previous_state": old_state,
                        "new_state": db_run.state,
                        "expected_version": old_version,
                        "new_version": old_version + 1,
                        "actor": "orchestrator",
                        "reason": f"Lifecycle {action_name}",
                        "correlation_id": db_run.run_id,
                        "causation_id": None
                    })
                    self.run_repository.append_history(history)
                    
                    audit_evt = type("AuditEventImpl", (), {
                        "event_id": str(uuid.uuid4()),
                        "run_id": db_run.run_id,
                        "event_type": f"lifecycle_{action_name}",
                        "metadata": {"state": db_run.state}
                    })
                    self.audit_repository.append(audit_evt)
                    run = updated_run
                else:
                    run = db_run

        try:
            # We fetch authoritative run state from DB for safety
            if self.transaction_boundary and self.run_repository:
                db_run = self.run_repository.get_run(run.run_id)
                if db_run:
                    run = db_run
            
            # Start preflight
            if run.state == LifecycleState.CREATED:
                if timeout_mgr: timeout_mgr.check()
                self.cancellation_manager.check_cancelled()
                def _do_preflight(r):
                    from .lifecycle import LifecycleController
                    LifecycleController(r, spec, decision, app).start_preflight()
                _execute_lifecycle("preflight", _do_preflight)
                
            if run.state == LifecycleState.FAILED:
                errors = run.preflight.errors if run.preflight.errors else ["Preflight failed or rejected."]
                return self._fail_and_audit(request, "rejected", errors, "Preflight failed")
                
            if run.state == LifecycleState.AUTHORIZATION_PENDING:
                if timeout_mgr: timeout_mgr.check()
                self.cancellation_manager.check_cancelled()
                def _do_auth(r):
                    from .lifecycle import LifecycleController
                    LifecycleController(r, spec, decision, app).authorize()
                _execute_lifecycle("authorize", _do_auth)
                
        except AuthorizationError as e:
            return self._fail_and_audit(request, "rejected", [f"Authorization rejected: {e}"], "Authorization failed")
        except InvalidStateTransitionError as e:
            return self._fail_and_audit(request, "failed", [f"Invalid lifecycle transition: {e}"], "Invalid transition")
        except OrchestrationTimeoutError as e:
            return self._fail_and_audit(request, "failed", [str(e)], "Timeout")
        except OrchestrationCancelledError as e:
            return self._fail_and_audit(request, "rejected", [str(e)], "Cancelled")
        except Exception as e:
            return self._fail_and_audit(request, "failed", [f"Lifecycle error: {e}"], "Lifecycle error")
            
        # Phase C & E: Adapter routing and planning"""
        
    content = re.sub(do_orch_regex, do_orch_new, content, flags=re.DOTALL)
    
    with open(path, "w") as f:
        f.write(content)

update_orchestrator()
