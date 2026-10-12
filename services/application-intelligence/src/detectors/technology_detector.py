import os
from collections import defaultdict
from typing import List, Dict

from ..models.technology import Technology, Evidence, TechnologyInventory
from .technology_registry import REGISTRY, TechnologyDefinition
from .manifest_detector import detect_dependencies_in_file
from .config_detector import detect_config_signatures
from .confidence import calculate_confidence

IGNORED_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 
    'build', 'dist', 'cache', 'coverage'
}

def analyze_application(source_path: str) -> TechnologyInventory:
    """
    Main entry point for analyzing a local application directory.
    Recursively scans the directory (safely) and detects technologies.
    """
    evidence_map: Dict[str, List[Evidence]] = defaultdict(list)
    version_map: Dict[str, str] = {}
    
    if not os.path.isdir(source_path):
        return TechnologyInventory(technologies=[])

    for root, dirs, files in os.walk(source_path):
        # Mutate dirs in-place to prevent os.walk from visiting ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        
        for file in files:
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, source_path)
            
            _, ext = os.path.splitext(file)
            
            # 1. Match File Extensions
            for tech in REGISTRY:
                if ext in tech.file_extensions:
                    evidence_map[tech.name].append(
                        Evidence(source=rel_path, type="file_extension", detail=ext)
                    )
            
            # 2. Match Manifest Files
            for tech in REGISTRY:
                if file in tech.manifest_files:
                    evidence_map[tech.name].append(
                        Evidence(source=rel_path, type="filename", detail=file)
                    )
            
            # 3. Parse Manifests for Dependencies
            # E.g., parse package.json, requirements.txt
            deps = detect_dependencies_in_file(filepath)
            if deps:
                # We have a manifest, map its dependencies to technologies
                for tech in REGISTRY:
                    for pkg_name in tech.package_names:
                        # Some package_names are exact, some might be substrings but for determinism we check exact
                        # or simple includes. Let's do exact match first.
                        if pkg_name in deps:
                            evidence_map[tech.name].append(
                                Evidence(source=rel_path, type="manifest_dependency", detail=pkg_name)
                            )
                            if deps[pkg_name]:
                                version_map[tech.name] = deps[pkg_name]
                        # For cases like "org.springframework.boot", if it's in pom.xml, we'd do substring match
                        else:
                            # Substring match for more complex identifiers (like maven groups or go modules)
                            for dep_key, dep_ver in deps.items():
                                if pkg_name in dep_key:
                                    evidence_map[tech.name].append(
                                        Evidence(source=rel_path, type="manifest_dependency", detail=dep_key)
                                    )
                                    if dep_ver:
                                        version_map[tech.name] = dep_ver

            # 4. Check config signatures (e.g., Kubernetes)
            sigs = detect_config_signatures(filepath)
            for sig in sigs:
                for tech in REGISTRY:
                    if sig == "Kubernetes" and tech.name == "Kubernetes":
                        evidence_map[tech.name].append(
                            Evidence(source=rel_path, type="configuration", detail="Kubernetes API signature")
                        )

    # 5. Build Final Technology Objects
    technologies = []
    for tech in REGISTRY:
        evs = evidence_map.get(tech.name, [])
        if evs:
            confidence = calculate_confidence(evs)
            # Only include if confidence is meaningful (e.g., > 0.0)
            if confidence > 0:
                technologies.append(Technology(
                    name=tech.name,
                    category=tech.category,
                    version=version_map.get(tech.name),
                    confidence=confidence,
                    evidence=evs
                ))
                
    return TechnologyInventory(technologies=technologies)
