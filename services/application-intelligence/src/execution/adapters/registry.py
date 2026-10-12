from typing import Dict, List, Optional
from .base import ExecutionAdapter
from .errors import AdapterResolutionError

class AdapterRegistry:
    def __init__(self):
        self._adapters: Dict[str, ExecutionAdapter] = {}
        
    def register(self, adapter: ExecutionAdapter):
        cap = adapter.capabilities()
        if cap.adapter_id in self._adapters:
            raise ValueError(f"Adapter {cap.adapter_id} already registered.")
        self._adapters[cap.adapter_id] = adapter
        
    def unregister(self, adapter_id: str):
        if adapter_id in self._adapters:
            del self._adapters[adapter_id]
            
    def get(self, adapter_id: str) -> Optional[ExecutionAdapter]:
        return self._adapters.get(adapter_id)
        
    def list(self) -> List[ExecutionAdapter]:
        return list(self._adapters.values())
        
    def resolve(self, fault_type: str, target_type: str) -> ExecutionAdapter:
        matching = []
        for adapter in self._adapters.values():
            cap = adapter.capabilities()
            if fault_type in cap.supported_fault_types and target_type in cap.supported_target_types:
                matching.append(adapter)
                
        if len(matching) == 0:
            raise AdapterResolutionError(f"No adapter found for fault_type={fault_type} target_type={target_type}")
        elif len(matching) > 1:
            raise AdapterResolutionError(f"Ambiguous adapter resolution for fault_type={fault_type} target_type={target_type}. Multiple adapters match.")
            
        return matching[0]
        
    def has_capability(self, capability: str) -> bool:
        for adapter in self._adapters.values():
            if capability in adapter.capabilities().required_capabilities:
                return True
        return False
