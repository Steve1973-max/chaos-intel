import re

def fix_orchestrator(path):
    with open(path, "r") as f:
        content = f.read()

    # Import CommitUncertaintyError at the top of the file
    content = content.replace(
        "from .errors import AuthorizationError, InvalidStateTransitionError",
        "from .errors import AuthorizationError, InvalidStateTransitionError\nfrom .persistence.interfaces import CommitUncertaintyError"
    )

    # In _do_orchestrate, check if db run is already processed
    old_fetch = """        try:
            # We fetch authoritative run state from DB for safety
            if self.transaction_boundary and self.run_repository:
                db_run = self.run_repository.get_run(run.run_id)
                if db_run:
                    run = db_run
            
            # Start preflight"""
            
    new_fetch = """        try:
            # We fetch authoritative run state from DB for safety
            if self.transaction_boundary and self.run_repository:
                db_run = self.run_repository.get_run(run.run_id)
                if db_run:
                    run = db_run

            if run.state not in (LifecycleState.CREATED, LifecycleState.AUTHORIZATION_PENDING):
                return self._fail_and_audit(request, "rejected", [f"Run is already in state {run.state} and cannot be re-orchestrated."], "Already orchestrated")
            
            # Start preflight"""
            
    content = content.replace(old_fetch, new_fetch)

    with open(path, "w") as f:
        f.write(content)

fix_orchestrator(r"C:\Users\steve\OneDrive\desktop\Major project\services\application-intelligence\src\execution\orchestrator.py")
