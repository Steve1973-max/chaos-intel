from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from pydantic import BaseModel, Field, field_validator
try:
    from .schemas import (
        ApplicationModel,
        Evidence,
        EvidenceTraceabilityError,
        InvalidInputError,
        PriorityBreakdown,
        SafetyViolationError,
        TestCandidate,
    )
except ImportError:
    from schemas import (  # type: ignore[no-redef]
        ApplicationModel,
        Evidence,
        EvidenceTraceabilityError,
        InvalidInputError,
        PriorityBreakdown,
        SafetyViolationError,
        TestCandidate,
    )


class AgentCapabilities(BaseModel):
    agent_id: str = Field(min_length=1)
    agent_type: str = Field(min_length=1)
    version: str = Field(default="1.0.0", min_length=1)
    deterministic: bool = True
    can_authorize_execution: bool = False
    supported_tasks: List[str] = Field(default_factory=list)

    @field_validator("can_authorize_execution")
    @classmethod
    def _forbid_execution_authorization(cls, v: bool) -> bool:
        if v is not False:
            raise SafetyViolationError(
                "Testing agents are strictly prohibited from authorizing chaos execution (can_authorize_execution must be False)."
            )
        return False


class TestSuggestion(BaseModel):
    """
    Model-agnostic suggestion produced by an IntelligenceProvider (deterministic or future LLM).
    AI may suggest test cases, but suggestions cannot authorize execution and must carry traceable evidence.
    """

    __test__ = False
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    test_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    expected_failure_mode: str = Field(min_length=1)
    priority: str = "medium"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    prerequisites: List[str] = Field(default_factory=list)
    suggested_observations: List[str] = Field(default_factory=list)
    related_risk_ids: List[str] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    execution_authorized: bool = False

    @field_validator("execution_authorized")
    @classmethod
    def _enforce_suggestion_not_authorized(cls, v: bool) -> bool:
        if v is not False:
            raise SafetyViolationError("AI test suggestions cannot authorize execution.")
        return False

    @field_validator("evidence")
    @classmethod
    def _enforce_suggestion_evidence(cls, v: List[Evidence]) -> List[Evidence]:
        if not v:
            raise EvidenceTraceabilityError("AI test suggestions must include at least one traceable Evidence item.")
        for item in v:
            if not (item.source and item.source.strip() and item.type and item.type.strip() and item.detail and item.detail.strip()):
                raise EvidenceTraceabilityError("Evidence items must have non-empty source, type, and detail.")
        return v


@runtime_checkable
class IntelligenceProvider(Protocol):
    """
    Model-agnostic interface for deterministic baseline or future LLM intelligence providers.
    Providers may suggest tests and enrich explanations, but never authorize execution.
    """

    @property
    def provider_id(self) -> str:
        ...

    @property
    def is_deterministic(self) -> bool:
        ...

    def suggest_test_cases(self, app: ApplicationModel) -> List[TestSuggestion]:
        ...

    def explain_priority(self, title: str, breakdown: PriorityBreakdown) -> str:
        ...


class DeterministicBaselineProvider:
    """
    Default deterministic baseline implementation of IntelligenceProvider.
    Uses rule-based architectural heuristics without external model calls.
    """

    @property
    def provider_id(self) -> str:
        return "deterministic-baseline-v1"

    @property
    def is_deterministic(self) -> bool:
        return True

    def suggest_test_cases(self, app: ApplicationModel) -> List[TestSuggestion]:
        """
        Deterministically suggests workflow resilience tests when multi-service dependency chains exist
        with traceable evidence.
        """
        suggestions: List[TestSuggestion] = []
        service_map = {s.service_id: s for s in app.services}

        # Identify multi-hop service chains A -> B -> C in dependencies
        adj: Dict[str, List[Any]] = {}
        for dep in sorted(app.dependencies, key=lambda d: (d.source_service_id, d.target_service_id or d.name)):
            if dep.target_service_id and dep.source_service_id != dep.target_service_id:
                adj.setdefault(dep.source_service_id, []).append(dep)

        for src_id in sorted(adj.keys()):
            for dep1 in adj[src_id]:
                mid_id = dep1.target_service_id
                if mid_id and mid_id in adj:
                    for dep2 in adj[mid_id]:
                        dst_id = dep2.target_service_id
                        if dst_id and dst_id != src_id:
                            evidence: List[Evidence] = []
                            evidence.extend(dep1.evidence)
                            evidence.extend(dep2.evidence)
                            if not evidence and src_id in service_map:
                                evidence.extend(service_map[src_id].evidence)
                            if not evidence:
                                continue

                            chain_id = f"{src_id}->{mid_id}->{dst_id}"
                            src_name = service_map[src_id].name if src_id in service_map else src_id
                            mid_name = service_map[mid_id].name if mid_id in service_map else mid_id
                            dst_name = service_map[dst_id].name if dst_id in service_map else dst_id
                            conf = round(min(dep1.confidence or 0.75, dep2.confidence or 0.75), 2)
                            if conf <= 0.0:
                                conf = 0.75

                            suggestions.append(
                                TestSuggestion(
                                    target_type="workflow",
                                    target_id=chain_id,
                                    test_type="workflow_resilience",
                                    title=f"End-to-end workflow resilience across {src_name} -> {mid_name} -> {dst_name}",
                                    hypothesis=(
                                        f"When downstream dependency '{dst_name}' experiences latency or degradation, "
                                        f"upstream workflow from '{src_name}' through '{mid_name}' degrades gracefully "
                                        f"without cascading failure."
                                    ),
                                    reason=(
                                        f"Multi-hop synchronous dependency chain detected ({chain_id}) susceptible to "
                                        f"cascading timeout amplification."
                                    ),
                                    expected_failure_mode=(
                                        f"Cascading request timeouts or thread-pool exhaustion propagating from "
                                        f"{dst_name} to {src_name}."
                                    ),
                                    priority="high",
                                    confidence=conf,
                                    prerequisites=[
                                        "Staging or isolated test environment verified",
                                        f"Distributed tracing active across {src_name}, {mid_name}, and {dst_name}",
                                    ],
                                    suggested_observations=[
                                        f"End-to-end latency on {src_name}",
                                        f"Circuit breaker state and timeout counters on {mid_name}",
                                        f"Error rate propagation from {dst_name}",
                                    ],
                                    evidence=evidence,
                                    execution_authorized=False,
                                )
                            )
        return suggestions

    def explain_priority(self, title: str, breakdown: PriorityBreakdown) -> str:
        return (
            f"Test '{title}' is ranked '{breakdown.priority_band}' (score={breakdown.total_score:.2f}/100) "
            f"based on severity={breakdown.severity_score:.2f}, risk={breakdown.risk_score:.2f}, "
            f"dependency_criticality={breakdown.dependency_criticality_score:.2f}, and "
            f"confidence={breakdown.confidence_score:.2f}."
        )


@runtime_checkable
class TestingAgent(Protocol):
    def capabilities(self) -> AgentCapabilities:
        ...


class AgentRegistry:
    """
    Deterministic registry for Testing Agents and model-agnostic IntelligenceProviders.
    Enforces that no registered agent or provider can authorize chaos execution.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, Any] = {}
        self._providers: Dict[str, IntelligenceProvider] = {}
        default_provider = DeterministicBaselineProvider()
        self.register_provider(default_provider)

    def register_agent(self, agent: Any, overwrite: bool = False) -> None:
        if agent is None or not hasattr(agent, "capabilities") or not callable(agent.capabilities):
            raise InvalidInputError("Registered agent must implement a callable capabilities() method.")

        caps = agent.capabilities()
        if not isinstance(caps, AgentCapabilities):
            raise InvalidInputError("agent.capabilities() must return an AgentCapabilities instance.")

        if caps.can_authorize_execution:
            raise SafetyViolationError(
                f"Agent '{caps.agent_id}' claims execution authorization capability, which is forbidden."
            )

        if caps.agent_id in self._agents and not overwrite:
            raise InvalidInputError(f"Agent '{caps.agent_id}' is already registered.")

        self._agents[caps.agent_id] = agent

    def get_agent(self, agent_id: str) -> Any:
        if agent_id not in self._agents:
            raise InvalidInputError(f"Agent '{agent_id}' is not registered.")
        return self._agents[agent_id]

    def resolve_by_type(self, agent_type: str) -> List[Any]:
        matches = [
            agent
            for _, agent in sorted(self._agents.items(), key=lambda item: item[0])
            if agent.capabilities().agent_type == agent_type
        ]
        return matches

    def list_agents(self) -> List[AgentCapabilities]:
        return [
            agent.capabilities()
            for _, agent in sorted(self._agents.items(), key=lambda item: item[0])
        ]

    def register_provider(self, provider: IntelligenceProvider, overwrite: bool = False) -> None:
        if provider is None or not isinstance(provider, IntelligenceProvider):
            raise InvalidInputError("Provider must satisfy the IntelligenceProvider protocol.")
        pid = provider.provider_id
        if not pid or not isinstance(pid, str):
            raise InvalidInputError("Provider must expose a non-empty string provider_id.")
        if pid in self._providers and not overwrite:
            raise InvalidInputError(f"IntelligenceProvider '{pid}' is already registered.")
        self._providers[pid] = provider

    def get_provider(self, provider_id: str = "deterministic-baseline-v1") -> IntelligenceProvider:
        if provider_id not in self._providers:
            raise InvalidInputError(f"IntelligenceProvider '{provider_id}' is not registered.")
        return self._providers[provider_id]

    def list_providers(self) -> List[str]:
        return sorted(self._providers.keys())
