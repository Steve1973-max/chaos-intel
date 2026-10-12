import re

def fix_orchestrator(path):
    with open(path, "r") as f:
        content = f.read()

    # Import CommitUncertaintyError
    content = content.replace("from .persistence.interfaces import OptimisticConcurrencyError", "from .persistence.interfaces import OptimisticConcurrencyError, CommitUncertaintyError")

    # Add except block
    old_except = "        except AuthorizationError as e:"
    new_except = """        except CommitUncertaintyError as e:
            return OrchestrationResponse(
                status="outcome_unknown",
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                safety_decision_id=decision.decision_id,
                adapter_id=None,
                mode=request.mode,
                errors=["Commit outcome is unknown. Please verify run state manually or retry."]
            )
        except AuthorizationError as e:"""
    content = content.replace(old_except, new_except)

    with open(path, "w") as f:
        f.write(content)

fix_orchestrator(r"C:\Users\steve\OneDrive\desktop\Major project\services\application-intelligence\src\execution\orchestrator.py")
