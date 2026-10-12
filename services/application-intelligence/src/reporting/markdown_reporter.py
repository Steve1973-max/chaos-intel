from .models import ApplicationReport
from typing import List, Any
import html

def escape_md(text: str) -> str:
    """Escapes Markdown sensitive characters in untrusted names/descriptions."""
    if not text:
        return ""
    # Very basic escaping to avoid injection, preserving readability
    text = str(text)
    for char in ['*', '_', '`', '#', '<', '>', '[', ']', '|']:
        text = text.replace(char, f'\\{char}')
    return text

def generate_markdown_report(report: ApplicationReport) -> str:
    lines: List[str] = []
    
    # Title
    lines.append(f"# CHAOS-INTEL Application Assessment: {escape_md(report.name)}")
    lines.append(f"**Application ID:** `{escape_md(report.application_id)}`")
    if report.repository_url:
        lines.append(f"**Repository:** `{escape_md(report.repository_url)}`")
    lines.append(f"**Generated At:** {report.generated_at}")
    lines.append("")
    
    if report.warnings:
        lines.append("## Limitations and Warnings")
        for w in report.warnings:
            lines.append(f"- {escape_md(w)}")
        lines.append("")
    
    # Overview
    lines.append("## 1. Application Overview")
    lines.append(f"- **Total Technologies:** {report.summaries.total_technologies}")
    lines.append(f"- **Total Services:** {report.summaries.total_services}")
    lines.append(f"- **Total Dependencies:** {report.summaries.total_dependencies}")
    lines.append(f"- **Total APIs:** {report.summaries.total_apis}")
    lines.append("")
    
    # Technology Stack
    if report.technologies:
        lines.append("## 2. Technology Stack")
        for tech in report.technologies:
            lines.append(f"- **{escape_md(tech.name)}** ({escape_md(tech.category)})")
        lines.append("")
    
    # Services and Dependencies
    if report.services or report.dependencies:
        lines.append("## 3. Services and Dependencies")
        for svc in report.services:
            lines.append(f"### Service: {escape_md(svc.name)}")
            if getattr(svc, 'technology', None):
                lines.append(f"- **Technology:** {escape_md(svc.technology)}")
            # Find dependencies for this service
            svc_deps = [d for d in report.dependencies if d.source_service_id == svc.service_id]
            if svc_deps:
                lines.append("- **Dependencies:**")
                for d in svc_deps:
                    lines.append(f"  - {escape_md(d.name)} ({escape_md(d.dependency_type)})")
            lines.append("")
            
    # API Inventory
    if report.apis:
        lines.append("## 4. API Inventory")
        for api in report.apis:
            lines.append(f"- **{escape_md(api.method)}** `{escape_md(api.path)}` (Protocol: {escape_md(api.protocol)})")
        lines.append("")
        
    # Architecture Overview
    lines.append("## 5. Architecture Overview")
    lines.append(f"The architecture contains {len(report.architecture.nodes)} nodes and {len(report.architecture.edges)} edges.")
    lines.append("")
    
    # Risk Assessment
    if report.risks:
        lines.append("## 6. Risk Assessment")
        lines.append("### Summary by Severity")
        for sev, count in report.summaries.risks_by_severity.items():
            lines.append(f"- **{sev}:** {count}")
        lines.append("")
        lines.append("### Detailed Findings")
        for risk in report.risks:
            lines.append(f"#### {escape_md(risk.title)}")
            lines.append(f"- **Severity:** {risk.severity}")
            lines.append(f"- **Category:** {risk.category}")
            lines.append(f"- **Target:** {escape_md(risk.target_type)} (`{escape_md(risk.target_id)}`)")
            lines.append(f"- **Description:** {escape_md(risk.description)}")
            lines.append("")
    
    # Test Candidates
    if report.test_candidates:
        lines.append("## 7. Recommended Test Candidates")
        lines.append("### Summary by Type")
        for tc_type, count in report.summaries.test_candidates_by_type.items():
            lines.append(f"- **{tc_type}:** {count}")
        lines.append("")
        lines.append("### Details")
        for tc in report.test_candidates:
            lines.append(f"#### {escape_md(tc.title)}")
            lines.append(f"- **Priority:** {tc.priority}")
            lines.append(f"- **Type:** {tc.test_type}")
            lines.append(f"- **Hypothesis:** {escape_md(tc.hypothesis)}")
            lines.append(f"- **Reason:** {escape_md(tc.reason)}")
            lines.append("")
            
    # Experiment Specifications
    if report.experiments:
        lines.append("## 8. Declarative Experiment Specifications")
        lines.append("### Summary by Fault Type")
        for ftype, count in report.summaries.experiments_by_fault_type.items():
            lines.append(f"- **{ftype}:** {count}")
        lines.append("")
        for exp in report.experiments:
            lines.append(f"#### Experiment: {escape_md(exp.name)}")
            lines.append(f"- **Status:** {exp.status}")
            lines.append(f"- **Target:** {escape_md(exp.target.name)}")
            lines.append(f"- **Fault Type:** {escape_md(exp.fault.type)}")
            lines.append(f"- **Hypothesis:** {escape_md(exp.hypothesis)}")
            lines.append("")
            
    # Safety and Policy
    if report.safety_decisions:
        lines.append("## 9. Safety and Policy Assessment")
        for sd in report.safety_decisions:
            lines.append(f"### Decision for Experiment `{escape_md(sd.experiment_id)}`")
            lines.append(f"- **Decision:** {sd.decision}")
            lines.append(f"- **Allowed:** {sd.allowed}")
            if sd.blockers:
                lines.append("- **Blockers:**")
                for b in sd.blockers:
                    lines.append(f"  - {escape_md(b)}")
            lines.append("")
            
    # Experiment Run History
    if report.experiment_runs:
        lines.append("## 10. Experiment Run History")
        for run in report.experiment_runs:
            lines.append(f"### Run `{escape_md(run.run_id)}` (Experiment: `{escape_md(run.experiment_id)}`)")
            lines.append(f"- **State:** {run.state}")
            lines.append(f"- **Created At:** {run.created_at}")
            if run.started_at:
                lines.append(f"- **Started At:** {run.started_at}")
            if run.completed_at:
                lines.append(f"- **Completed At:** {run.completed_at}")
            if run.error:
                lines.append(f"- **Error:** {escape_md(run.error.message)}")
            lines.append("")
            
    return "\n".join(lines)
