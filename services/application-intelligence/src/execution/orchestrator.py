import traceback
from typing import Optional
from .orchestration_models import OrchestrationRequest, OrchestrationResponse
from .orchestration_errors import InvalidInputError, IDMismatchError
from .lifecycle import LifecycleController
from .states import LifecycleState
from .router import AdapterRouter
from .adapters.registry import AdapterRegistry
from .adapters.dry_run import DryRunAdapter
from .adapters.context import ExecutionContext
from .errors import AuthorizationError, InvalidStateTransitionError
from .persistence.interfaces import CommitUncertaintyError, IdempotencyConflictError as PersistenceIdempotencyConflictError
from .reliability import (
    LeaseManager, LeaseContext, IdempotencyManager, TimeoutManager, 
    CancellationManager, AuditLogger, AuditEvent,
    LeaseAcquisitionError, LeaseOwnershipError, IdempotencyConflictError, 
    InvalidIdempotencyKeyError, OrchestrationTimeoutError, OrchestrationCancelledError
)

# Global in-memory instances for process-scope reliability guarantees
_global_lease_manager = LeaseManager()
_global_idempotency_manager = IdempotencyManager()
_global_audit_logger = AuditLogger()

class OrchestrationController:
    def __init__(
        self, 
        registry=None,
        lease_manager: Optional[LeaseManager] = None,
        idempotency_manager: Optional[IdempotencyManager] = None,
        audit_logger: Optional[AuditLogger] = None,
        run_repository=None,
        audit_repository=None,
        transaction_boundary=None,
        idempotency_repository=None,
        lease_repository=None
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
        self.cancellation_manager = CancellationManager()
        self.idempotency_repository = idempotency_repository
        self.lease_repository = lease_repository

    def orchestrate(
        self, 
        request: OrchestrationRequest,
        idempotency_key: Optional[str] = None,
        timeout_sec: Optional[float] = None
    ) -> OrchestrationResponse:
        # Phase A: Input validation
        if request.mode != "dry_run":
            return self._fail(request, "rejected", ["Live mode is not supported. Use dry_run mode."])
            
        if request.application_model.application_id != request.experiment_specification.application_id:
            return self._fail(request, "failed", ["Application ID mismatch"])
            
        if request.experiment_specification.experiment_id != request.safety_decision.experiment_id:
            return self._fail(request, "failed", ["Experiment ID mismatch"])
            
        if request.experiment_run.experiment_id != request.experiment_specification.experiment_id:
            return self._fail(request, "failed", ["Run Experiment ID mismatch"])

        if request.experiment_run.safety_decision_id != request.safety_decision.decision_id:
            return self._fail(request, "failed", ["Run Safety Decision ID mismatch"])
            
        run = request.experiment_run
        spec = request.experiment_specification
        decision = request.safety_decision
        app = request.application_model
        
        # Phase A2: Idempotency Check
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
            except (IdempotencyConflictError, PersistenceIdempotencyConflictError, InvalidIdempotencyKeyError) as e:
                return self._fail(request, "rejected", [str(e)])

        # Timeout setup
        timeout_mgr = TimeoutManager(timeout_sec) if timeout_sec is not None else None
        
        # Phase A3: Cancellation Check
        try:
            self.cancellation_manager.check_cancelled()
        except OrchestrationCancelledError as e:
            return self._fail(request, "rejected", [str(e)])

        # Prevent re-using already active/terminal runs
        if request.experiment_run.state not in (LifecycleState.CREATED, LifecycleState.AUTHORIZATION_PENDING):
            return self._fail(request, "rejected", [f"Run is already in state {request.experiment_run.state} and cannot be re-orchestrated."])

        import uuid
        attempt_owner_id = idempotency_owner or str(uuid.uuid4())
        
        # Authoritative pre-intent contract: Record immutable reservation owner prior to execution
        if not isinstance(request.experiment_run.metadata, dict):
            request.experiment_run.metadata = {}
        if "owner_id" not in request.experiment_run.metadata:
            request.experiment_run.metadata["owner_id"] = attempt_owner_id

        # Durable fencing integration
        lease_resource_id = f"run:{request.experiment_run.run_id}"
        durable_lease = None
        
        if self.lease_repository:
            lease_ttl = int(timeout_sec) if timeout_sec is not None else 300
            try:
                durable_lease = self.lease_repository.acquire(lease_resource_id, attempt_owner_id, lease_ttl)
            except LeaseAcquisitionError as e:
                return self._fail(request, "rejected", [f"Lease acquisition failed: {e}"])
            except Exception as e:
                return self._fail(request, "failed", [f"Lease acquisition error: {e}"])
                
        try:
            if durable_lease:
                try:
                    return self._do_orchestrate(request, request.experiment_run, spec, decision, app, timeout_mgr, idempotency_key, attempt_owner_id, durable_lease)
                finally:
                    try:
                        self.lease_repository.release(lease_resource_id, attempt_owner_id, durable_lease.fencing_token)
                    except Exception:
                        pass
            else:
                with LeaseContext(self.lease_manager, request.experiment_run.run_id, attempt_owner_id, timeout_sec):
                    return self._do_orchestrate(request, request.experiment_run, spec, decision, app, timeout_mgr, idempotency_key, attempt_owner_id)
        except LeaseAcquisitionError as e:
            return self._fail(request, "rejected", [str(e)])
        except Exception as e:
            return self._fail(request, "failed", [str(e)])

    def _do_orchestrate(
        self, request: OrchestrationRequest, initial_run, spec, decision, app, timeout_mgr, idempotency_key, idempotency_owner=None, durable_lease=None
    ) -> OrchestrationResponse:
        import uuid
        run = initial_run
        
        def _execute_lifecycle(action_name, action_func):
            nonlocal run
            if not (self.transaction_boundary and self.run_repository and self.audit_repository):
                action_func(run)
                return

            context_mgr = self.transaction_boundary.transaction()
            if durable_lease and hasattr(self.transaction_boundary, 'fenced_transaction'):
                context_mgr = self.transaction_boundary.fenced_transaction(
                    durable_lease.resource_id, durable_lease.owner_id, durable_lease.fencing_token
                )

            with context_mgr:
                db_run = self.run_repository.get_run(run.run_id)
                if not db_run:
                    if run.state != LifecycleState.CREATED:
                        raise InvalidStateTransitionError("Cannot create a run in a non-CREATED state.")
                    self.run_repository.create_run(run)
                    db_run = self.run_repository.get_run(run.run_id)
                elif isinstance(getattr(db_run, "metadata", None), dict) and "owner_id" not in db_run.metadata and idempotency_owner:
                    db_run.metadata["owner_id"] = idempotency_owner

                if db_run.state not in (LifecycleState.CREATED, LifecycleState.AUTHORIZATION_PENDING, LifecycleState.AUTHORIZED):
                    raise AuthorizationError(f"Run is already in state {db_run.state} and cannot be re-orchestrated.")

                old_state = db_run.state
                old_version = db_run.version
                
                # Execute lifecycle on the DB run copy
                action_func(db_run)
                
                if db_run.state != old_state:
                    from .persistence.interfaces import OptimisticConcurrencyError, CommitUncertaintyError
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

            if run.state not in (LifecycleState.CREATED, LifecycleState.AUTHORIZATION_PENDING):
                return self._fail_and_audit(request, "rejected", [f"Run is already in state {run.state} and cannot be re-orchestrated."], "Already orchestrated")
            
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
                
        except CommitUncertaintyError as e:
            return OrchestrationResponse(
                status="outcome_unknown",
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                safety_decision_id=decision.decision_id,
                adapter_id=None,
                mode=request.mode,
                errors=["Commit outcome is unknown. Please verify run state manually or retry."]
            )
        except LeaseOwnershipError as e:
            return self._fail_and_audit(request, "rejected", [f"Lease ownership lost before execution: {e}"], "Lost lease ownership")
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
            
        # Phase C & E: Adapter routing and planning
        router = AdapterRouter(self.registry)
        try:
            if timeout_mgr: timeout_mgr.check()
            self.cancellation_manager.check_cancelled()
            adapter, plan = router.route(spec, run, decision, app, mode="dry_run")
        except OrchestrationTimeoutError as e:
            return self._fail_and_audit(request, "failed", [str(e)], "Timeout")
        except OrchestrationCancelledError as e:
            return self._fail_and_audit(request, "rejected", [str(e)], "Cancelled")
        except Exception as e:
            return self._fail_and_audit(request, "failed", [f"Routing/Planning failed: {e}"], "Routing/Planning failed")
            
        # Phase E2: Execution Intent Boundary
        # The transition to SETUP acts as the durable execution intent marker.
        # It MUST be durably committed before adapter invocation can proceed.
        try:
            if timeout_mgr: timeout_mgr.check()
            self.cancellation_manager.check_cancelled()
            def _do_setup(r):
                from .lifecycle import LifecycleController
                LifecycleController(r, spec, decision, app).setup()
            _execute_lifecycle("setup", _do_setup)
        except CommitUncertaintyError as e:
            return OrchestrationResponse(
                status="outcome_unknown",
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                safety_decision_id=decision.decision_id,
                adapter_id=adapter.capabilities().adapter_id,
                mode=request.mode,
                errors=["Commit outcome is unknown during execution intent. Cannot safely invoke adapter."]
            )
        except LeaseOwnershipError as e:
            return self._fail_and_audit(request, "rejected", [f"Lease ownership lost before intent commit: {e}"], "Lost lease ownership", adapter_id=adapter.capabilities().adapter_id)
        except InvalidStateTransitionError as e:
            return self._fail_and_audit(request, "failed", [f"Invalid lifecycle transition during intent: {e}"], "Invalid transition", adapter_id=adapter.capabilities().adapter_id)
        except OrchestrationTimeoutError as e:
            return self._fail_and_audit(request, "failed", [str(e)], "Timeout", adapter_id=adapter.capabilities().adapter_id)
        except OrchestrationCancelledError as e:
            return self._fail_and_audit(request, "rejected", [str(e)], "Cancelled", adapter_id=adapter.capabilities().adapter_id)
        except Exception as e:
            return self._fail_and_audit(request, "failed", [f"Execution intent failed: {e}"], "Intent error", adapter_id=adapter.capabilities().adapter_id)

        # Phase F: Dry-run Execution
        # We explicitly DO NOT call lifecycle.run_experiment(), lifecycle.observe(), etc.
        # to ensure we do not fabricate real execution history.
        # A dry-run ends at SETUP state with a simulated plan and result.
        
        context = ExecutionContext(
            run=run,
            experiment=spec,
            safety_decision=decision,
            application_model=app,
            mode="dry_run",
            adapter_id=adapter.capabilities().adapter_id,
            correlation_id=run.run_id
        )
        
        try:
            if timeout_mgr: timeout_mgr.check()
            self.cancellation_manager.check_cancelled()
            # We can invoke the adapter's methods to get a simulated result,
            # but we do not mutate the ExperimentRun's state using the LifecycleController.
            final_result = adapter.cleanup(context)
        except OrchestrationTimeoutError as e:
            return self._fail_and_audit(request, "failed", [str(e)], "Timeout", adapter_id=adapter.capabilities().adapter_id)
        except OrchestrationCancelledError as e:
            return self._fail_and_audit(request, "rejected", [str(e)], "Cancelled", adapter_id=adapter.capabilities().adapter_id)
        except Exception as e:
            return self._fail_and_audit(request, "failed", [f"Execution failed: {e}"], "Execution error", adapter_id=adapter.capabilities().adapter_id)
            
        response = OrchestrationResponse(
            status="completed",
            run_id=run.run_id,
            experiment_id=spec.experiment_id,
            safety_decision_id=decision.decision_id,
            adapter_id=adapter.capabilities().adapter_id,
            mode="dry_run",
            plan=plan,
            result=final_result,
            errors=[]
        )
        
        self.audit_logger.log(AuditEvent(
            run_id=run.run_id,
            application_id=app.application_id,
            experiment_id=spec.experiment_id,
            event_type="orchestration_completed",
            current_state=run.state,
            outcome="success",
            correlation_id=run.run_id
        ))
        
        if idempotency_key:
            if self.idempotency_repository and idempotency_owner:
                try:
                    context_mgr = None
                    if self.transaction_boundary:
                        if durable_lease and hasattr(self.transaction_boundary, 'fenced_transaction'):
                            context_mgr = self.transaction_boundary.fenced_transaction(
                                durable_lease.resource_id, durable_lease.owner_id, durable_lease.fencing_token
                            )
                        else:
                            context_mgr = self.transaction_boundary.transaction()
                    
                    if context_mgr:
                        with context_mgr:
                            self.idempotency_repository.publish_result(
                                application_id=app.application_id,
                                experiment_id=spec.experiment_id,
                                key=idempotency_key,
                                owner=idempotency_owner,
                                result=response.model_dump(mode="json")
                            )
                    else:
                        self.idempotency_repository.publish_result(
                            application_id=app.application_id,
                            experiment_id=spec.experiment_id,
                            key=idempotency_key,
                            owner=idempotency_owner,
                            result=response.model_dump(mode="json")
                        )
                except LeaseOwnershipError as e:
                    return OrchestrationResponse(
                        status="outcome_unknown",
                        run_id=run.run_id,
                        experiment_id=spec.experiment_id,
                        safety_decision_id=decision.decision_id,
                        adapter_id=None,
                        mode=request.mode,
                        errors=["Lost lease ownership before publishing idempotency result.", str(e)]
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
                self.idempotency_manager.store_result(idempotency_key, response)
            
        return response

    def _fail_and_audit(self, request: OrchestrationRequest, status: str, errors: list, reason: str, adapter_id: Optional[str] = None):
        resp = self._fail(request, status, errors, adapter_id)
        
        if idempotency_key_attr := getattr(request, "_idempotency_key", None):
            # We could store failures too if desired, but typically we only store successful/terminal outcomes
            pass
            
        self.audit_logger.log(AuditEvent(
            run_id=request.experiment_run.run_id,
            application_id=request.application_model.application_id,
            experiment_id=request.experiment_specification.experiment_id,
            event_type="orchestration_failed",
            current_state=request.experiment_run.state,
            outcome="failure",
            reason=reason,
            correlation_id=request.experiment_run.run_id,
            metadata={"errors": errors}
        ))
        return resp
        
    def _fail(self, request: OrchestrationRequest, status: str, errors: list, adapter_id: Optional[str] = None) -> OrchestrationResponse:
        return OrchestrationResponse(
            status=status,
            run_id=request.experiment_run.run_id,
            experiment_id=request.experiment_specification.experiment_id,
            safety_decision_id=request.safety_decision.decision_id,
            adapter_id=adapter_id,
            mode=request.mode,
            errors=errors
        )
