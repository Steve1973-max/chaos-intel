import json
from ..models.architecture import ArchitectureGraph

def serialize_graph(graph: ArchitectureGraph) -> str:
    # Model dump ensures everything is json-safe (pydantic handles sorting if dicts, but we already sorted the lists)
    return graph.model_dump_json(indent=2)
