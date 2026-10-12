from typing import List, Dict, Any
from ..models.application import ApplicationModel
from ..models.risk import RiskFinding
from .rules.single_point_of_failure import SinglePointOfFailureRule
from .rules.critical_dependency import CriticalDependencyRule
from .rules.availability_concentration import AvailabilityConcentrationRule
from .rules.external_dependency import ExternalDependencyRule
from .rules.cyclic_dependency import CyclicDependencyRule
from .rules.dependency_concentration import DependencyConcentrationRule
from .rules.unresolved_dependency import UnresolvedDependencyRule
from .rules.api_concentration import ApiConcentrationRule
from .rules.unauthenticated_api import UnauthenticatedApiRule

class RiskAnalysisResult:
    def __init__(self, findings: List[RiskFinding], summary: Dict[str, Any]):
        self.findings = findings
        self.summary = summary

def deduplicate_findings(findings: List[RiskFinding]) -> List[RiskFinding]:
    deduped = {}
    for f in findings:
        key = (f.application_id, f.risk_type, f.target_id)
        if key not in deduped:
            deduped[key] = f
        else:
            # Merge evidence
            existing_f = deduped[key]
            existing_ev = {f"{e.source}:{e.type}:{e.detail}" for e in existing_f.evidence}
            for ev in f.evidence:
                ev_str = f"{ev.source}:{ev.type}:{ev.detail}"
                if ev_str not in existing_ev:
                    existing_f.evidence.append(ev)
                    existing_ev.add(ev_str)
                    
            # Use highest confidence
            existing_f.confidence = max(existing_f.confidence, f.confidence)
            
    return list(deduped.values())

def generate_summary(findings: List[RiskFinding]) -> Dict[str, Any]:
    summary = {
        "total_findings": len(findings),
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0
    }
    for f in findings:
        sev = f.severity.lower()
        if sev in summary:
            summary[sev] += 1
            
    return summary

def analyze_risks(app: ApplicationModel) -> RiskAnalysisResult:
    rules = [
        SinglePointOfFailureRule(),
        CriticalDependencyRule(),
        AvailabilityConcentrationRule(),
        ExternalDependencyRule(),
        CyclicDependencyRule(),
        DependencyConcentrationRule(),
        UnresolvedDependencyRule(),
        ApiConcentrationRule(),
        UnauthenticatedApiRule()
    ]
    
    all_findings = []
    for rule in rules:
        findings = rule.evaluate(app)
        all_findings.extend(findings)
        
    deduped = deduplicate_findings(all_findings)
    
    # Sort for determinism
    sorted_findings = sorted(deduped, key=lambda f: f.risk_id)
    
    summary = generate_summary(sorted_findings)
    return RiskAnalysisResult(findings=sorted_findings, summary=summary)
