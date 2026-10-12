import os
from typing import Dict, List, Tuple
from urllib.parse import urlparse

def parse_env_file(filepath: str) -> List[Tuple[str, str, str]]:
    """
    Parses a .env file safely.
    Returns a list of (key, target_host, dependency_type).
    Does NOT return actual secret values.
    """
    dependencies = []
    if not os.path.exists(filepath):
        return dependencies
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"\'')
                    
                    # Heuristics for targets
                    target = None
                    dep_type = "unknown"
                    
                    if "DATABASE_URL" in key or "DB_URL" in key or "POSTGRES" in key or "MYSQL" in key:
                        dep_type = "database"
                    elif "REDIS" in key or "CACHE" in key:
                        dep_type = "cache"
                    elif "RABBITMQ" in key or "KAFKA" in key:
                        dep_type = "message_queue"
                    elif "API_URL" in key or key.endswith("_URL"):
                        dep_type = "http" if "http" in val else "unknown"

                    # Try to parse URL to extract host safely
                    if "://" in val:
                        try:
                            parsed = urlparse(val)
                            target = parsed.hostname
                            if not target:
                                target = val.split("://")[1].split("/")[0].split("@")[-1].split(":")[0]
                        except Exception:
                            pass
                    
                    if target:
                        dependencies.append((key, target, dep_type))
    except Exception:
        pass
        
    return dependencies
