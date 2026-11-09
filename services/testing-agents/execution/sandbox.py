import ipaddress
import re
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import urlparse
from pydantic import BaseModel, Field

try:
    from ..schemas import SafetyDecision, SafetyViolationError, TestPlan, TestingAgentError
except ImportError:
    from schemas import SafetyDecision, SafetyViolationError, TestPlan, TestingAgentError  # type: ignore[no-redef]


class ExecutionSafetyError(SafetyViolationError):
    """Base exception for test execution safety violations."""


class UnauthorizedPlanError(ExecutionSafetyError):
    """Raised when attempting to execute a TestPlan without explicit approval."""


class TargetOutOfScopeError(ExecutionSafetyError):
    """Raised when a target URL or host is outside the permitted SandboxPolicy scope."""


class PrivateNetworkTargetBlockedError(ExecutionSafetyError):
    """Raised when a target resolves to localhost, loopback, link-local, or private network without explicit authorization."""


class DestructiveActionBlockedError(ExecutionSafetyError):
    """Raised when a destructive HTTP method or action is attempted while allow_destructive_actions is False."""


class ExecutionCancelledError(TestingAgentError):
    """Raised when a test execution is cancelled via CancellationToken."""


class ExecutionApproval(BaseModel):
    """
    Explicit authorization record required by TestExecutionEngine before executing any TestPlan.
    """

    approval_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved: bool = True
    safety_decision_id: Optional[str] = None
    notes: Optional[str] = None


class SandboxPolicy(BaseModel):
    """
    Defines the strict execution boundary and permitted target scope for automated test execution.
    """

    allowed_hosts: List[str] = Field(default_factory=list)
    allowed_schemes: List[str] = Field(default_factory=lambda: ["http", "https"])
    allow_localhost: bool = False
    allow_private_network: bool = False
    allow_destructive_actions: bool = False
    max_concurrency: int = Field(default=4, ge=1, le=64)
    default_timeout_seconds: float = Field(default=10.0, gt=0.0, le=300.0)


class SecretRedactor:
    """
    Prevents credentials, tokens, cookies, API keys, and connection strings from leaking
    into structured logs, step details, or evidence references.
    """

    SECRET_KEYS: Set[str] = {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "x-api-key",
        "private_key",
        "access_key",
        "credential",
        "credentials",
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "client_secret",
        "connection_string",
    }

    _AUTH_SCHEME_RE = re.compile(r"\b(Bearer|Basic|Token|ApiKey)\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
    _CONN_URI_RE = re.compile(r"\b(postgres|postgresql|mysql|mongodb|redis|amqp)://[^\s\"']+", re.IGNORECASE)

    @classmethod
    def redact_string(cls, text: str) -> str:
        if not text:
            return text
        redacted = cls._AUTH_SCHEME_RE.sub(r"\1 ***REDACTED***", text)
        redacted = cls._CONN_URI_RE.sub("***REDACTED_URI***", redacted)
        return redacted

    @classmethod
    def redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cleaned: Dict[str, Any] = {}
            for k, v in data.items():
                key_lower = str(k).strip().lower()
                if any(sec in key_lower for sec in cls.SECRET_KEYS):
                    cleaned[k] = "***REDACTED***"
                else:
                    cleaned[k] = cls.redact(v)
            return cleaned
        if isinstance(data, list):
            return [cls.redact(item) for item in data]
        if isinstance(data, tuple):
            return tuple(cls.redact(item) for item in data)
        if isinstance(data, str):
            return cls.redact_string(data)
        return data


class TargetSandbox:
    """
    Enforces safety invariants prior to and during test execution:
    - Explicit plan authorization
    - Target URL scheme and host allowlist validation
    - Blocking localhost/loopback/private network/link-local targets unless explicitly configured
    - Blocking destructive methods/actions by default
    """

    ALWAYS_BLOCKED_HOSTS: Set[str] = {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata",
        "100.100.100.200",
    }
    DESTRUCTIVE_HTTP_METHODS: Set[str] = {"DELETE", "DROP", "PURGE"}

    def __init__(self, policy: Optional[SandboxPolicy] = None) -> None:
        self.policy = policy or SandboxPolicy()
        self._normalized_allowed_hosts: Set[str] = {
            h.strip().lower() for h in self.policy.allowed_hosts if h and h.strip()
        }
        self._normalized_schemes: Set[str] = {
            s.strip().lower() for s in self.policy.allowed_schemes if s and s.strip()
        }

    @staticmethod
    def validate_plan_authorization(
        plan: TestPlan,
        approval: Optional[Union[ExecutionApproval, SafetyDecision]],
    ) -> None:
        if plan is None or not isinstance(plan, TestPlan):
            raise UnauthorizedPlanError("A valid TestPlan is required for execution.")

        if approval is None:
            raise UnauthorizedPlanError(
                f"TestPlan '{plan.plan_id}' cannot be executed without an explicit ExecutionApproval or approved SafetyDecision."
            )

        if isinstance(approval, ExecutionApproval):
            if not approval.approved:
                raise UnauthorizedPlanError(f"ExecutionApproval '{approval.approval_id}' is not approved.")
            if approval.plan_id != plan.plan_id:
                raise UnauthorizedPlanError(
                    f"ExecutionApproval plan_id '{approval.plan_id}' does not match TestPlan '{plan.plan_id}'."
                )
            if approval.application_id != plan.application_id:
                raise UnauthorizedPlanError(
                    f"ExecutionApproval application_id '{approval.application_id}' does not match TestPlan '{plan.application_id}'."
                )
            return

        if isinstance(approval, SafetyDecision):
            if not approval.allowed or approval.decision != "approved":
                raise UnauthorizedPlanError(
                    f"SafetyDecision '{approval.decision_id}' has decision='{approval.decision}' (allowed={approval.allowed}); execution is blocked."
                )
            if approval.application_id != plan.application_id:
                raise UnauthorizedPlanError(
                    f"SafetyDecision application_id '{approval.application_id}' does not match TestPlan '{plan.application_id}'."
                )
            return

        raise UnauthorizedPlanError(f"Unsupported approval object type: {type(approval).__name__}")

    def validate_url(self, url: str) -> str:
        if not url or not isinstance(url, str) or not url.strip():
            raise TargetOutOfScopeError("Target URL must be a non-empty string.")

        parsed = urlparse(url.strip())
        scheme = (parsed.scheme or "").lower()
        if scheme not in self._normalized_schemes:
            raise TargetOutOfScopeError(
                f"URL scheme '{scheme or '<empty>'}' is not permitted. Allowed schemes: {sorted(self._normalized_schemes)}."
            )

        if parsed.username or parsed.password:
            raise ExecutionSafetyError("Credentials embedded in target URLs are forbidden.")

        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            raise TargetOutOfScopeError(f"Target URL '{url}' is missing a valid hostname.")

        # 1. Unconditionally block cloud metadata endpoints
        if hostname in self.ALWAYS_BLOCKED_HOSTS:
            raise PrivateNetworkTargetBlockedError(
                f"Target host '{hostname}' is a restricted metadata endpoint and is unconditionally blocked."
            )

        # 2. Check IP literal or localhost classifications
        is_localhost = hostname in ("localhost", "localhost.localdomain", "0.0.0.0", "::1")
        is_private_net = hostname.endswith(".local") or hostname.endswith(".internal")

        try:
            ip_obj = ipaddress.ip_address(hostname)
            if ip_obj.is_link_local or str(ip_obj).startswith("169.254."):
                raise PrivateNetworkTargetBlockedError(
                    f"Link-local/metadata IP address '{hostname}' is unconditionally blocked."
                )
            if ip_obj.is_loopback or ip_obj.is_unspecified:
                is_localhost = True
            elif ip_obj.is_private or ip_obj.is_reserved or ip_obj.is_multicast:
                is_private_net = True
        except ValueError:
            # Not an IP literal; hostname checks apply
            if hostname.startswith("127."):
                is_localhost = True

        if is_localhost and not self.policy.allow_localhost:
            raise PrivateNetworkTargetBlockedError(
                f"Target host '{hostname}' resolves to localhost/loopback, which is blocked unless allow_localhost=True."
            )

        if is_private_net and not self.policy.allow_private_network:
            raise PrivateNetworkTargetBlockedError(
                f"Target host '{hostname}' is a private network target, which is blocked unless allow_private_network=True."
            )

        # 3. Enforce explicit host allowlist so arbitrary external systems are never tested
        if not self._normalized_allowed_hosts:
            raise TargetOutOfScopeError(
                f"Target host '{hostname}' rejected: SandboxPolicy.allowed_hosts is empty; arbitrary targets are forbidden."
            )

        if hostname not in self._normalized_allowed_hosts:
            raise TargetOutOfScopeError(
                f"Target host '{hostname}' is not in permitted SandboxPolicy.allowed_hosts: {sorted(self._normalized_allowed_hosts)}."
            )

        return url.strip()

    def validate_http_method(self, method: str) -> str:
        if not method or not isinstance(method, str):
            raise ExecutionSafetyError("HTTP method must be a non-empty string.")
        normalized = method.strip().upper()
        if normalized in self.DESTRUCTIVE_HTTP_METHODS and not self.policy.allow_destructive_actions:
            raise DestructiveActionBlockedError(
                f"Destructive HTTP method '{normalized}' is blocked by default unless allow_destructive_actions=True."
            )
        return normalized

    def validate_action(self, action_name: str, destructive: bool = False) -> None:
        if destructive and not self.policy.allow_destructive_actions:
            raise DestructiveActionBlockedError(
                f"Destructive action '{action_name}' is blocked by default unless allow_destructive_actions=True."
            )

