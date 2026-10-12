from src.detectors.confidence import calculate_confidence
from src.models.technology import Evidence

def test_confidence_empty():
    assert calculate_confidence([]) == 0.0

def test_confidence_manifest():
    ev = [Evidence(source="package.json", type="manifest_dependency", detail="react")]
    assert calculate_confidence(ev) == 0.8

def test_confidence_multiple_signals():
    ev = [
        Evidence(source="package.json", type="manifest_dependency", detail="react"),
        Evidence(source="src/App.tsx", type="file_extension", detail=".tsx")
    ]
    # 0.8 + 0.4 = 1.2 -> capped at 0.99
    assert calculate_confidence(ev) == 0.99
