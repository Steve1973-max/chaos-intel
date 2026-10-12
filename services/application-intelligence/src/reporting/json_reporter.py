import json
import jsonschema
from .models import ApplicationReport

def generate_json_report(report: ApplicationReport) -> str:
    """
    Generate a deterministic JSON string representation of the ApplicationReport.
    """
    # model_dump(mode='json') ensures dates, enums, etc. are properly serialized to JSON-compatible types
    data = report.model_dump(mode='json')
    
    # Validate against formal JSON Schema to confirm conformance
    schema = ApplicationReport.model_json_schema()
    jsonschema.validate(instance=data, schema=schema)
    
    # Dump to JSON with sorted keys to ensure determinism
    # ensure_ascii=False ensures it is UTF-8 compatible as requested
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
