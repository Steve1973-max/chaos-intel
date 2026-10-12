import re

def fix_tests(path):
    with open(path, "r") as f:
        content = f.read()

    # Replace MockRun with ExperimentRun
    content = content.replace('run = type("MockRun", (), {', 'from src.models.experiment_run import ExperimentRun\n    run = ExperimentRun(**{')
    content = content.replace('    })\n    repo.create_run(run)', '    })\n    repo.create_run(run)')
    # Wait, the end parenthesis of the dictionary might need to be fixed
    content = content.replace('        "safety_decision_id": "sd-1"\n    })', '        "safety_decision_id": "sd-1"\n    })')
    
    # Also transition_state now requires payload
    content = content.replace('repo.transition_state(run_id, 1, "AUTHORIZATION_PENDING")', 
                              'run.state = "AUTHORIZATION_PENDING"\n            run.version = 2\n            repo.transition_state(run_id, 1, "AUTHORIZATION_PENDING", run)')

    with open(path, "w") as f:
        f.write(content)

fix_tests(r"C:\Users\steve\OneDrive\desktop\Major project\services\application-intelligence\tests\test_persistence_history.py")

def fix_integration(path):
    with open(path, "r") as f:
        content = f.read()

    content = content.replace('run = type("MockRun", (), {', 'from src.models.experiment_run import ExperimentRun\n    run = ExperimentRun(**{')

    content = content.replace('repo.transition_state(run_id, expected_version=1, new_state="APPROVED")', 
                              'run.state = "APPROVED"\n    run.version = 2\n    repo.transition_state(run_id, 1, "APPROVED", run)')

    content = content.replace('repo.transition_state(run_id, expected_version=1, new_state="EXECUTING")', 
                              'run.state = "EXECUTING"\n        run.version = 2\n        repo.transition_state(run_id, 1, "EXECUTING", run)')

    content = content.replace('repo.transition_state(run_id, expected_version=1, new_state="FAILING")', 
                              'run.state = "FAILING"\n            run.version = 2\n            repo.transition_state(run_id, 1, "FAILING", run)')

    with open(path, "w") as f:
        f.write(content)
        
fix_integration(r"C:\Users\steve\OneDrive\desktop\Major project\services\application-intelligence\tests\test_persistence_integration.py")
