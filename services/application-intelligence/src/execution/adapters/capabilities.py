from pydantic import BaseModel
from typing import List

class AdapterCapabilities(BaseModel):
    adapter_id: str
    adapter_name: str
    supported_fault_types: List[str]
    supported_target_types: List[str]
    required_capabilities: List[str]
    version: str
