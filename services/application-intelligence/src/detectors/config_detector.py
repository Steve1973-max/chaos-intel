import os

def detect_config_signatures(filepath: str) -> list[str]:
    """Reads a file to find specific configuration signatures (like Kubernetes YAMLs)."""
    signatures_found = []
    try:
        # Don't read huge files
        if os.path.getsize(filepath) > 1024 * 1024:
            return signatures_found
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(8192) # Read first 8KB
            
            if "apiVersion: apps/v1" in content or "kind: Deployment" in content:
                signatures_found.append("Kubernetes")
    except Exception:
        pass
        
    return signatures_found
