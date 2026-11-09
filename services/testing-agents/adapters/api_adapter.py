import asyncio
import inspect
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional
import jsonschema
from pydantic import BaseModel, Field

try:
    from ..execution.execution_context import IsolatedExecutionContext, utcnow_iso
    from ..execution.result_collector import ExecutionErrorDetail, StepExecutionResult
    from ..execution.sandbox import (
        ExecutionCancelledError,
        ExecutionSafetyError,
        SecretRedactor,
    )
    from ..schemas import TestCase
    from .base import (
        AdapterExecutionOutput,
        AdapterMetadata,
        BaseTestExecutionAdapter,
        UncertainOperationError,
    )
except ImportError:
    from execution.execution_context import IsolatedExecutionContext, utcnow_iso  # type: ignore[no-redef]
    from execution.result_collector import ExecutionErrorDetail, StepExecutionResult  # type: ignore[no-redef]
    from execution.sandbox import (  # type: ignore[no-redef]
        ExecutionCancelledError,
        ExecutionSafetyError,
        SecretRedactor,
    )
    from schemas import TestCase  # type: ignore[no-redef]
    from adapters.base import (  # type: ignore[no-redef]
        AdapterExecutionOutput,
        AdapterMetadata,
        BaseTestExecutionAdapter,
        UncertainOperationError,
    )


class HttpResponseData(BaseModel):
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Any = None
    raw_text: str = ""
    latency_ms: float = Field(ge=0.0)


class ApiTestAdapter(BaseTestExecutionAdapter):
    """
    Executes functional and resilience API tests with:
    - HTTP method, URL scope, and destructive-method safety validation
    - Headers, authentication configuration (Bearer, ApiKey, Basic) with full secret redaction
    - Request timeouts and high-precision latency measurement
    - Status code, JSON field, and Draft-07 JSON Schema response validation
    - Zero automatic replay of uncertain mutating requests
    """

    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, http_transport: Optional[Callable[..., Any]] = None) -> None:
        self._http_transport = http_transport or self._default_urllib_transport

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            adapter_id="api-adapter-v1",
            adapter_type="api",
            version="1.0.0",
            supported_target_types=["api", "service", "dependency", "external_dependency"],
            supported_test_types=[
                "api_resilience",
                "availability",
                "latency",
                "dependency_resilience",
                "degradation",
            ],
            supports_live_chaos=False,
        )

    @staticmethod
    def _build_auth_headers(auth_cfg: Optional[Dict[str, Any]]) -> Dict[str, str]:
        if not auth_cfg or not isinstance(auth_cfg, dict):
            return {}
        auth_type = str(auth_cfg.get("type", "")).strip().lower()
        if auth_type == "bearer" and auth_cfg.get("token"):
            return {"Authorization": f"Bearer {auth_cfg['token']}"}
        if auth_type in ("api_key", "apikey") and auth_cfg.get("key"):
            header_name = str(auth_cfg.get("header", "X-API-Key"))
            return {header_name: str(auth_cfg["key"])}
        if auth_type == "basic" and auth_cfg.get("credentials"):
            return {"Authorization": f"Basic {auth_cfg['credentials']}"}
        return {}

    @staticmethod
    async def _default_urllib_transport(
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[Any],
        timeout_seconds: float,
    ) -> HttpResponseData:
        def _sync_call() -> HttpResponseData:
            data_bytes: Optional[bytes] = None
            req_headers = dict(headers)
            if body is not None:
                if isinstance(body, (dict, list)):
                    data_bytes = json.dumps(body).encode("utf-8")
                    req_headers.setdefault("Content-Type", "application/json")
                elif isinstance(body, str):
                    data_bytes = body.encode("utf-8")
                elif isinstance(body, bytes):
                    data_bytes = body

            req = urllib.request.Request(url=url, data=data_bytes, headers=req_headers, method=method)
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    raw_bytes = resp.read()
                    latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                    raw_text = raw_bytes.decode("utf-8", errors="replace")
                    parsed_body: Any = raw_text
                    try:
                        parsed_body = json.loads(raw_text)
                    except Exception:
                        pass
                    return HttpResponseData(
                        status_code=int(resp.status),
                        headers={k: v for k, v in resp.headers.items()},
                        body=parsed_body,
                        raw_text=raw_text,
                        latency_ms=latency_ms,
                    )
            except urllib.error.HTTPError as http_err:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                raw_bytes = http_err.read() if http_err.fp else b""
                raw_text = raw_bytes.decode("utf-8", errors="replace")
                parsed_body = raw_text
                try:
                    parsed_body = json.loads(raw_text)
                except Exception:
                    pass
                return HttpResponseData(
                    status_code=int(http_err.code),
                    headers={k: v for k, v in (http_err.headers.items() if http_err.headers else [])},
                    body=parsed_body,
                    raw_text=raw_text,
                    latency_ms=latency_ms,
                )

        return await asyncio.to_thread(_sync_call)

    def _extract_api_spec(self, test_case: TestCase, context: IsolatedExecutionContext) -> Dict[str, Any]:
        spec = dict(test_case.metadata.get("api_spec", {}))
        if "url" not in spec:
            base_url = str(context.variables.get("base_url", "http://test.local")).rstrip("/")
            path = str(spec.get("path", "/health"))
            if not path.startswith("/"):
                path = "/" + path
            spec["url"] = f"{base_url}{path}"
        spec.setdefault("method", "GET")
        spec.setdefault("expected_status", 200)
        return spec

    async def execute(
        self, test_case: TestCase, context: IsolatedExecutionContext
    ) -> AdapterExecutionOutput:
        context.register_cleanup(lambda: self.cleanup(context))
        context.check_cancelled()

        spec = self._extract_api_spec(test_case, context)
        url = str(spec.get("url", ""))
        raw_method = str(spec.get("method", "GET"))
        timeout_sec = float(spec.get("timeout_seconds", context.timeout_seconds))
        step_results: List[StepExecutionResult] = []

        # Step 1: Validate target URL and HTTP method against sandbox
        s1_start = utcnow_iso()
        t_s1 = time.perf_counter()
        try:
            validated_url = context.sandbox.validate_url(url)
            validated_method = context.sandbox.validate_http_method(raw_method)
        except ExecutionSafetyError as safety_err:
            s1_end = utcnow_iso()
            dur_s1 = round((time.perf_counter() - t_s1) * 1000.0, 3)
            err_detail = ExecutionErrorDetail(
                error_type=type(safety_err).__name__,
                message=str(safety_err),
                failed_step_number=1,
                failed_stage="precondition",
                failed_target=url,
                outcome_uncertain=False,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=1,
                    step_name="Validate API target scope and method policy",
                    stage="precondition",
                    status="failed",
                    started_at=s1_start,
                    ended_at=s1_end,
                    duration_ms=dur_s1,
                    details={"url": url, "method": raw_method},
                    error=err_detail,
                    evidence_refs=[],
                )
            )
            raise

        s1_end = utcnow_iso()
        dur_s1 = round((time.perf_counter() - t_s1) * 1000.0, 3)
        headers: Dict[str, str] = dict(spec.get("headers") or {})
        headers.update(self._build_auth_headers(spec.get("auth")))
        redacted_req_headers = SecretRedactor.redact(headers)

        step_results.append(
            StepExecutionResult(
                step_number=1,
                step_name="Validate API target scope and method policy",
                stage="precondition",
                status="passed",
                started_at=s1_start,
                ended_at=s1_end,
                duration_ms=dur_s1,
                details={
                    "url": validated_url,
                    "method": validated_method,
                    "headers": redacted_req_headers,
                },
                evidence_refs=[],
            )
        )

        # Step 2: Execute HTTP request and measure latency (no automatic retry on uncertain outcomes)
        context.check_cancelled()
        s2_start = utcnow_iso()
        t_s2 = time.perf_counter()
        try:
            call_coro = self._http_transport(
                method=validated_method,
                url=validated_url,
                headers=headers,
                body=spec.get("body"),
                timeout_seconds=timeout_sec,
            )
            if inspect.isawaitable(call_coro):
                resp: HttpResponseData = await asyncio.wait_for(call_coro, timeout=timeout_sec)
            else:
                resp = call_coro
        except asyncio.TimeoutError as te:
            s2_end = utcnow_iso()
            dur_s2 = round((time.perf_counter() - t_s2) * 1000.0, 3)
            is_uncertain = validated_method in self.MUTATING_METHODS
            err_detail = ExecutionErrorDetail(
                error_type="TimeoutError",
                message=f"API request '{validated_method} {validated_url}' timed out after {timeout_sec}s.",
                failed_step_number=2,
                failed_stage="step",
                failed_target=validated_url,
                outcome_uncertain=is_uncertain,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=2,
                    step_name=f"Execute {validated_method} {validated_url}",
                    stage="step",
                    status="timed_out",
                    started_at=s2_start,
                    ended_at=s2_end,
                    duration_ms=dur_s2,
                    details={"url": validated_url, "method": validated_method, "timeout_seconds": timeout_sec},
                    error=err_detail,
                    evidence_refs=[],
                )
            )
            return AdapterExecutionOutput(
                status="timed_out",
                step_results=step_results,
                error_details=err_detail,
                metadata={"outcome_uncertain": is_uncertain},
            )
        except ExecutionCancelledError:
            raise
        except UncertainOperationError as uoe:
            s2_end = utcnow_iso()
            dur_s2 = round((time.perf_counter() - t_s2) * 1000.0, 3)
            err_detail = ExecutionErrorDetail(
                error_type="UncertainOperationError",
                message=str(uoe),
                failed_step_number=2,
                failed_stage="step",
                failed_target=validated_url,
                outcome_uncertain=True,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=2,
                    step_name=f"Execute {validated_method} {validated_url}",
                    stage="step",
                    status="unknown",
                    started_at=s2_start,
                    ended_at=s2_end,
                    duration_ms=dur_s2,
                    details={"url": validated_url, "method": validated_method, "replayed": False},
                    error=err_detail,
                    evidence_refs=[],
                )
            )
            return AdapterExecutionOutput(
                status="unknown",
                step_results=step_results,
                error_details=err_detail,
                metadata={"outcome_uncertain": True, "automatic_replay": False},
            )
        except Exception as exc:
            s2_end = utcnow_iso()
            dur_s2 = round((time.perf_counter() - t_s2) * 1000.0, 3)
            is_uncertain = validated_method in self.MUTATING_METHODS
            step_status = "unknown" if is_uncertain else "failed"
            err_detail = ExecutionErrorDetail(
                error_type=type(exc).__name__,
                message=f"HTTP transport error on '{validated_method} {validated_url}': {exc}",
                failed_step_number=2,
                failed_stage="step",
                failed_target=validated_url,
                outcome_uncertain=is_uncertain,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=2,
                    step_name=f"Execute {validated_method} {validated_url}",
                    stage="step",
                    status=step_status,  # type: ignore[arg-type]
                    started_at=s2_start,
                    ended_at=s2_end,
                    duration_ms=dur_s2,
                    details={"url": validated_url, "method": validated_method, "replayed": False},
                    error=err_detail,
                    evidence_refs=[],
                )
            )
            return AdapterExecutionOutput(
                status=step_status,  # type: ignore[arg-type]
                step_results=step_results,
                error_details=err_detail,
                metadata={"outcome_uncertain": is_uncertain, "automatic_replay": False},
            )

        s2_end = utcnow_iso()
        dur_s2 = round((time.perf_counter() - t_s2) * 1000.0, 3)
        ev_trace = context.add_evidence(
            evidence_type="http_trace",
            uri=f"trace://http/{context.execution_id}/step-2",
            summary=f"{validated_method} {validated_url} -> HTTP {resp.status_code} ({resp.latency_ms:.2f}ms)",
            metadata={
                "method": validated_method,
                "url": validated_url,
                "request_headers": redacted_req_headers,
                "status_code": resp.status_code,
                "response_headers": SecretRedactor.redact(resp.headers),
                "latency_ms": resp.latency_ms,
            },
        )
        step_results.append(
            StepExecutionResult(
                step_number=2,
                step_name=f"Execute {validated_method} {validated_url}",
                stage="step",
                status="passed",
                started_at=s2_start,
                ended_at=s2_end,
                duration_ms=dur_s2,
                latency_ms=resp.latency_ms,
                details={
                    "status_code": resp.status_code,
                    "latency_ms": resp.latency_ms,
                },
                evidence_refs=[ev_trace.evidence_id],
            )
        )

        # Step 3: Validate status code, latency SLA, expected JSON fields, and response JSON Schema
        s3_start = utcnow_iso()
        t_s3 = time.perf_counter()
        validation_errors: List[str] = []

        expected_status = spec.get("expected_status", 200)
        allowed_statuses = (
            set(expected_status)
            if isinstance(expected_status, (list, tuple, set))
            else {int(expected_status)}
        )
        if resp.status_code not in allowed_statuses:
            validation_errors.append(
                f"Expected HTTP status in {sorted(allowed_statuses)}, got {resp.status_code}."
            )

        max_latency_ms = spec.get("max_latency_ms")
        if max_latency_ms is not None and resp.latency_ms > float(max_latency_ms):
            validation_errors.append(
                f"Response latency {resp.latency_ms:.2f}ms exceeded SLA threshold {float(max_latency_ms):.2f}ms."
            )

        response_schema = spec.get("response_schema")
        if response_schema and isinstance(response_schema, dict):
            validator = jsonschema.Draft7Validator(response_schema)
            schema_errs = list(validator.iter_errors(resp.body))
            if schema_errs:
                validation_errors.append(
                    f"Response JSON schema validation failed: {schema_errs[0].message}"
                )

        expected_fields = spec.get("expected_json_fields")
        if expected_fields and isinstance(expected_fields, dict):
            if not isinstance(resp.body, dict):
                validation_errors.append("Expected JSON object response body for field assertions.")
            else:
                for k, expected_val in expected_fields.items():
                    if resp.body.get(k) != expected_val:
                        validation_errors.append(
                            f"Response field '{k}' expected {expected_val!r}, got {resp.body.get(k)!r}."
                        )

        s3_end = utcnow_iso()
        dur_s3 = round((time.perf_counter() - t_s3) * 1000.0, 3)

        if validation_errors:
            joined_msg = " ".join(validation_errors)
            err_detail = ExecutionErrorDetail(
                error_type="ApiAssertionError",
                message=joined_msg,
                failed_step_number=3,
                failed_stage="postcondition",
                failed_target=validated_url,
                outcome_uncertain=False,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=3,
                    step_name="Validate HTTP response status, latency, and schema",
                    stage="postcondition",
                    status="failed",
                    started_at=s3_start,
                    ended_at=s3_end,
                    duration_ms=dur_s3,
                    latency_ms=resp.latency_ms,
                    details={"validation_errors": validation_errors},
                    error=err_detail,
                    evidence_refs=[ev_trace.evidence_id],
                )
            )
            return AdapterExecutionOutput(
                status="failed",
                step_results=step_results,
                error_details=err_detail,
                metadata={"latency_ms": resp.latency_ms, "status_code": resp.status_code},
            )

        # Save response body to context variables for downstream workflow steps if needed
        if isinstance(resp.body, dict):
            context.variables["last_api_response"] = SecretRedactor.redact(resp.body)

        step_results.append(
            StepExecutionResult(
                step_number=3,
                step_name="Validate HTTP response status, latency, and schema",
                stage="postcondition",
                status="passed",
                started_at=s3_start,
                ended_at=s3_end,
                duration_ms=dur_s3,
                latency_ms=resp.latency_ms,
                details={
                    "status_code": resp.status_code,
                    "latency_ms": resp.latency_ms,
                    "schema_validated": bool(response_schema),
                },
                evidence_refs=[ev_trace.evidence_id],
            )
        )

        return AdapterExecutionOutput(
            status="passed",
            step_results=step_results,
            error_details=None,
            metadata={"latency_ms": resp.latency_ms, "status_code": resp.status_code},
        )

