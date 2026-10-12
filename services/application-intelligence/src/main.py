import os
import hashlib
from .models.application import ApplicationModel
from .detectors.technology_detector import analyze_application as detect_technologies
from .detectors.service_detector import discover_services
from .detectors.dependency_detector import discover_dependencies
from .detectors.api_detector import discover_apis
from .graph.graph_builder import build_architecture_graph
from .graph.graph_validator import validate_graph
from .risk.engine import analyze_risks
from .strategy.engine import generate_test_candidates
from .experiment.engine import generate_experiment_specifications
from .safety.engine import generate_safety_decisions

def generate_app_id(source_path: str) -> str:
    # Use the absolute normalized path of the root to avoid collisions between identically named folders
    abs_path = os.path.abspath(source_path)
    hash_obj = hashlib.md5(abs_path.encode('utf-8'))
    return f"app-{hash_obj.hexdigest()[:8]}"

def generate_app_name(source_path: str) -> str:
    basename = os.path.basename(os.path.abspath(source_path))
    return basename if basename else "application"

def analyze_application(source_path: str) -> ApplicationModel:
    app_id = generate_app_id(source_path)
    app_name = generate_app_name(source_path)
    
    # 1. Technology Detection
    tech_inv = detect_technologies(source_path)
    technologies = tech_inv.technologies
    
    # 2. Service Discovery
    services = discover_services(source_path, app_id)
    
    # 3. Dependency Discovery
    dependencies = discover_dependencies(source_path, services)
    
    # 4. API Discovery
    apis = discover_apis(source_path, services, app_id)
    
    # 5. Architecture Graph Construction
    architecture = build_architecture_graph(services, dependencies, apis, technologies)
    
    # 6. Validation
    errors = validate_graph(architecture)
    diagnostics = {}
    if errors:
        diagnostics["graph_validation_errors"] = errors
    
    # Assemble temp model without risks for risk evaluation
    temp_model = ApplicationModel(
        application_id=app_id,
        name=app_name,
        technologies=technologies,
        services=services,
        dependencies=dependencies,
        apis=apis,
        architecture=architecture
    )
        
    # 7. Risk Analysis
    risk_result = analyze_risks(temp_model)
    if risk_result.summary:
        diagnostics["risk_summary"] = risk_result.summary
    
    # 8. Test Candidate Generation
    temp_model_with_risks = ApplicationModel(
        application_id=app_id,
        name=app_name,
        technologies=technologies,
        services=services,
        dependencies=dependencies,
        apis=apis,
        architecture=architecture,
        risks=risk_result.findings
    )
    test_candidates = generate_test_candidates(temp_model_with_risks)
    
    # 9. Experiment Specification Generation
    temp_model_with_candidates = ApplicationModel(
        application_id=app_id,
        name=app_name,
        technologies=technologies,
        services=services,
        dependencies=dependencies,
        apis=apis,
        architecture=architecture,
        risks=risk_result.findings,
        test_candidates=test_candidates
    )
    experiments = generate_experiment_specifications(temp_model_with_candidates)

    # 10. Safety & Policy Validation
    temp_model_with_experiments = ApplicationModel(
        application_id=app_id,
        name=app_name,
        technologies=technologies,
        services=services,
        dependencies=dependencies,
        apis=apis,
        architecture=architecture,
        risks=risk_result.findings,
        test_candidates=test_candidates,
        experiments=experiments
    )
    safety_decisions = generate_safety_decisions(temp_model_with_experiments)

    # 11. Application Model Assembly (final)
    model = ApplicationModel(
        application_id=app_id,
        name=app_name,
        technologies=technologies,
        services=services,
        dependencies=dependencies,
        apis=apis,
        architecture=architecture,
        risks=risk_result.findings,
        test_candidates=test_candidates,
        experiments=experiments,
        safety_decisions=safety_decisions,
        metadata={"diagnostics": diagnostics} if diagnostics else {}
    )
    
    return model

def analyze_services_and_dependencies(source_path: str, app_id: str = "app-default"):
    class ServiceDependencyResult:
        def __init__(self, services, dependencies, apis, diagnostics=None):
            self.services = services
            self.dependencies = dependencies
            self.apis = apis
            self.diagnostics = diagnostics or {}
    
    services = discover_services(source_path, app_id)
    dependencies = discover_dependencies(source_path, services)
    apis = discover_apis(source_path, services, app_id)
    return ServiceDependencyResult(services=services, dependencies=dependencies, apis=apis)

if __name__ == "__main__":
    import argparse
    import json
    import sys
    
    parser = argparse.ArgumentParser(description="CHAOS-INTEL Application Intelligence CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # Report command
    report_parser = subparsers.add_parser("report", help="Generate reports from ApplicationModel JSON")
    report_parser.add_argument("--input", required=True, help="Input ApplicationModel JSON file path")
    report_parser.add_argument("--format", required=True, choices=["json", "markdown", "mermaid"], help="Output format")
    report_parser.add_argument("--output", required=True, help="Output file path")
    
    args = parser.parse_args()
    
    if args.command == "report":
        from .reporting import build_application_report, generate_json_report, generate_markdown_report, generate_mermaid_report
        
        # Prevent input overwrite
        try:
            if os.path.exists(args.input) and os.path.exists(args.output):
                if os.path.samefile(args.input, args.output):
                    print(f"Error: Output file path '{args.output}' resolves to the same file as input.", file=sys.stderr)
                    sys.exit(1)
            else:
                if os.path.realpath(args.input) == os.path.realpath(args.output):
                    print(f"Error: Output file path '{args.output}' resolves to the same file as input.", file=sys.stderr)
                    sys.exit(1)
        except Exception as e:
            print(f"Error checking file paths: {e}", file=sys.stderr)
            sys.exit(1)
            
        try:
            with open(args.input, "r", encoding="utf-8") as f:
                input_data = json.load(f)
            
            # Use validate to load Pydantic model
            app_model = ApplicationModel.model_validate(input_data)
        except Exception as e:
            print(f"Error reading or validating input model: {e}", file=sys.stderr)
            sys.exit(1)
            
        report = build_application_report(app_model)
        
        if args.format == "json":
            output_content = generate_json_report(report)
        elif args.format == "markdown":
            output_content = generate_markdown_report(report)
        elif args.format == "mermaid":
            output_content = generate_mermaid_report(report)
        else:
            print(f"Error: Unknown format '{args.format}'", file=sys.stderr)
            sys.exit(1)
            
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_content)
            print(f"Successfully generated {args.format} report at {args.output}")
        except Exception as e:
            print(f"Error writing output file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        if args.command is None:
            # Not an error to run without command, just print help, but typically exit 1 or 0
            sys.exit(0)
