def calculate_priority(risk_severity: str, confidence: float, is_central: bool = False) -> str:
    """
    Calculate deterministic priority based on risk severity, confidence, and architectural centrality.
    """
    severity_map = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    pri_map = {0: "low", 1: "low", 2: "medium", 3: "high", 4: "critical", 5: "critical"}
    
    score = severity_map.get(risk_severity.lower(), 1)
    
    # Confidence adjusts score up or down if it's very low or high
    if confidence >= 0.8:
        # High confidence maintains or elevates slightly
        pass
    elif confidence < 0.5:
        # Low confidence drops priority
        score -= 1
        
    if is_central:
        score += 1
        
    # Bound score
    score = max(1, min(score, 4))
    return pri_map[score]
