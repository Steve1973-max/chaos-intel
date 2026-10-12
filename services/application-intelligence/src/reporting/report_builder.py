import re
from datetime import datetime, timezone
from typing import Optional, Any
from ..models.application import ApplicationModel
from .models import ApplicationReport
from .summary import calculate_summaries

SECRET_PATTERNS = re.compile(r'(password|secret|token|api_key|private_key|access_key|credential)', re.IGNORECASE)

def redact_secrets(data: Any) -> Any:
    """Recursively sweep dictionaries and lists for sensitive keys and mask their values."""
    if isinstance(data, dict):
        redacted = {}
        for k, v in data.items():
            if isinstance(k, str) and SECRET_PATTERNS.search(k) and isinstance(v, str):
                redacted[k] = "***REDACTED***"
            else:
                redacted[k] = redact_secrets(v)
        return redacted
    elif isinstance(data, list):
        return [redact_secrets(item) for item in data]
    else:
        return data

def build_application_report(
    application_model: ApplicationModel, 
    generated_at: Optional[str] = None
) -> ApplicationReport:
    """
    Deterministically build an ApplicationReport from an ApplicationModel.
    Does not mutate the input model.
    """
    
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    
    # 1. Deep copy and redact the whole model natively
    app_data = application_model.model_dump()
    redacted_data = redact_secrets(app_data)
    redacted_model = ApplicationModel.model_validate(redacted_data)
    
    # 2. Calculate deterministic summaries
    summaries = calculate_summaries(redacted_model)
    
    warnings = []
    if not redacted_model.technologies:
        warnings.append("No technologies detected.")
    if not redacted_model.services:
        warnings.append("No services detected.")
        
    return ApplicationReport(
        generated_at=timestamp,
        application_id=redacted_model.application_id,
        name=redacted_model.name,
        repository_url=redacted_model.repository_url,
        technologies=redacted_model.technologies,
        services=redacted_model.services,
        dependencies=redacted_model.dependencies,
        apis=redacted_model.apis,
        architecture=redacted_model.architecture,
        risks=redacted_model.risks,
        test_candidates=redacted_model.test_candidates,
        experiments=redacted_model.experiments,
        safety_decisions=redacted_model.safety_decisions,
        experiment_runs=redacted_model.experiment_runs,
        summaries=summaries,
        metadata=redacted_model.metadata,
        warnings=warnings
    )
