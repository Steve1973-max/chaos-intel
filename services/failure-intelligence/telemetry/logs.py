"""Structured log parsing and management for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from schemas.telemetry import LogLevel, StructuredLogEntry, utcnow_iso

_ERROR_TYPE_REGEX = re.compile(r"([A-Z][a-zA-Z0-9]+(?:Error|Exception|Fault|Timeout))")


class LogProcessor:
    """Parses, enriches, and filters structured logs."""

    @staticmethod
    def parse_entry(
        raw: Dict[str, Any] | str,
        default_service_id: str = "unknown",
        correlation_id: Optional[str] = None,
    ) -> StructuredLogEntry:
        """Parse raw JSON dict or text line into StructuredLogEntry."""
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except Exception:
                data = {"message": raw}
                stripped = raw.strip()
                for lvl in ("FATAL", "CRITICAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG"):
                    if stripped.upper().startswith(f"{lvl}:") or stripped.upper().startswith(f"[{lvl}]") or stripped.upper().startswith(f"{lvl} "):
                        data["level"] = lvl
                        break
        else:
            data = dict(raw)

        # Timestamp
        ts = data.get("timestamp") or data.get("time") or data.get("@timestamp") or utcnow_iso()
        service_id = str(data.get("service_id") or data.get("service") or default_service_id)

        # Level
        raw_lvl = str(data.get("level") or data.get("severity") or "INFO").upper()
        level: LogLevel = "INFO"
        if "FATAL" in raw_lvl or "CRIT" in raw_lvl:
            level = "FATAL"
        elif "ERR" in raw_lvl:
            level = "ERROR"
        elif "WARN" in raw_lvl:
            level = "WARN"
        elif "DEBUG" in raw_lvl:
            level = "DEBUG"

        message = str(data.get("message") or data.get("msg") or "")

        # Tracing identifiers
        trace_id = data.get("trace_id") or data.get("traceId")
        span_id = data.get("span_id") or data.get("spanId")
        corr_id = data.get("correlation_id") or data.get("correlationId") or correlation_id

        # Error type detection
        error_type = data.get("error_type") or data.get("error")
        if not error_type and level in ("ERROR", "FATAL"):
            match = _ERROR_TYPE_REGEX.search(message)
            if match:
                error_type = match.group(1)

        log_id = str(data.get("log_id") or f"log-{uuid.uuid4().hex[:8]}")
        attrs = {
            k: v
            for k, v in data.items()
            if k
            not in (
                "log_id",
                "timestamp",
                "time",
                "@timestamp",
                "service_id",
                "service",
                "level",
                "severity",
                "message",
                "msg",
                "trace_id",
                "traceId",
                "span_id",
                "spanId",
                "correlation_id",
                "correlationId",
                "error_type",
                "error",
                "stack_trace",
            )
        }

        return StructuredLogEntry(
            log_id=log_id,
            timestamp=ts,
            service_id=service_id,
            level=level,
            message=message,
            trace_id=trace_id,
            span_id=span_id,
            correlation_id=corr_id,
            error_type=error_type,
            stack_trace=data.get("stack_trace"),
            attributes=attrs,
        )

    @classmethod
    def filter_errors(
        cls,
        logs: List[StructuredLogEntry],
        service_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> List[StructuredLogEntry]:
        """Extract ERROR and FATAL logs, optionally filtered by service or correlation ID."""
        errs: List[StructuredLogEntry] = []
        for l in logs:
            if l.level in ("ERROR", "FATAL"):
                if service_id and l.service_id != service_id:
                    continue
                if correlation_id and l.correlation_id != correlation_id:
                    continue
                errs.append(l)
        return errs
