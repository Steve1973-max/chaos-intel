from typing import Dict, Any, List
from collections import defaultdict
from ..models.application import ApplicationModel
from .models import ReportSummaries

def calculate_summaries(model: ApplicationModel) -> ReportSummaries:
    summaries = ReportSummaries(
        total_technologies=len(model.technologies),
        total_services=len(model.services),
        total_dependencies=len(model.dependencies),
        total_apis=len(model.apis)
    )

    for risk in model.risks:
        sev = risk.severity if risk.severity else "unknown"
        summaries.risks_by_severity[sev] = summaries.risks_by_severity.get(sev, 0) + 1
        
    for tc in model.test_candidates:
        tc_type = tc.test_type if tc.test_type else "unknown"
        prio = tc.priority if tc.priority else "unknown"
        summaries.test_candidates_by_type[tc_type] = summaries.test_candidates_by_type.get(tc_type, 0) + 1
        summaries.test_candidates_by_priority[prio] = summaries.test_candidates_by_priority.get(prio, 0) + 1
        
    for exp in model.experiments:
        ftype = exp.fault.type if exp.fault and exp.fault.type else "unknown"
        summaries.experiments_by_fault_type[ftype] = summaries.experiments_by_fault_type.get(ftype, 0) + 1

    for sd in model.safety_decisions:
        status = sd.decision if getattr(sd, "decision", None) else "unknown"
        summaries.safety_decisions_by_status[status] = summaries.safety_decisions_by_status.get(status, 0) + 1

    for run in model.experiment_runs:
        state = run.state if run.state else "unknown"
        summaries.experiment_runs_by_state[state] = summaries.experiment_runs_by_state.get(state, 0) + 1

    # Sort dictionary keys for deterministic output
    summaries.risks_by_severity = dict(sorted(summaries.risks_by_severity.items()))
    summaries.test_candidates_by_type = dict(sorted(summaries.test_candidates_by_type.items()))
    summaries.test_candidates_by_priority = dict(sorted(summaries.test_candidates_by_priority.items()))
    summaries.experiments_by_fault_type = dict(sorted(summaries.experiments_by_fault_type.items()))
    summaries.safety_decisions_by_status = dict(sorted(summaries.safety_decisions_by_status.items()))
    summaries.experiment_runs_by_state = dict(sorted(summaries.experiment_runs_by_state.items()))

    return summaries
