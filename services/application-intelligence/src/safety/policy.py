class PolicyConstants:
    POLICY_VERSION = "1.0.0"
    
    BLAST_RADIUS_LIMITS = {
        "single_service": 1,
        "single_dependency": 1,
        "single_api": 1,
        "single_external_dependency": 1,
        "multiple_services": 2,
        "unknown": 0
    }
    
    SUPPORTED_FAULTS = {
        "availability",
        "latency",
        "network_partition",
        "packet_loss",
        "connection_exhaustion",
        "resource_cpu",
        "resource_memory",
        "dependency_unavailable",
        "dependency_slow",
        "queue_backlog"
    }
    
    SUPPORTED_ENVIRONMENTS = {
        "development",
        "test",
        "staging",
        "production",
        "unknown"
    }

    MAX_DURATION_SECONDS = 300
    
    CAPABILITY_MAPPINGS = {
        "service_stop": "service_control",
        "network_delay": "network_control",
        "network_isolation": "network_control",
        "message_consumption_delay": "message_control"
    }
