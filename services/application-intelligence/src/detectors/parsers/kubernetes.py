import os
import yaml
from typing import Dict, Any, List

def parse_kubernetes_manifest(filepath: str) -> List[Dict[str, Any]]:
    """
    Safely parses Kubernetes YAML files to detect services/deployments.
    """
    results = []
    if not os.path.exists(filepath):
        return results
        
    if os.path.getsize(filepath) > 5 * 1024 * 1024:
        return results

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            docs = yaml.safe_load_all(f)
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                
                kind = doc.get('kind')
                if kind in ('Deployment', 'StatefulSet', 'DaemonSet', 'Service'):
                    metadata = doc.get('metadata', {})
                    name = metadata.get('name')
                    if name:
                        results.append({
                            'name': name,
                            'kind': kind,
                            'type': 'unknown'
                        })
    except Exception:
        pass
        
    return results
