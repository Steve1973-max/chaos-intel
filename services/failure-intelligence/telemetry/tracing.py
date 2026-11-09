"""Distributed trace processing and correlation for CHAOS-INTEL Phase 4."""

from __future__ import annotations

from typing import Dict, List, Optional, Set
from schemas.telemetry import TraceSpan


class TraceTree:
    """Represents an assembled trace with parent-child span hierarchy."""

    def __init__(self, trace_id: str, spans: List[TraceSpan]) -> None:
        self.trace_id = trace_id
        self.spans = spans
        self.spans_by_id: Dict[str, TraceSpan] = {s.span_id: s for s in spans}
        self.children_by_parent: Dict[str, List[TraceSpan]] = {}
        self.root_span: Optional[TraceSpan] = None

        for s in spans:
            if not s.parent_span_id or s.parent_span_id not in self.spans_by_id:
                self.root_span = s
            else:
                self.children_by_parent.setdefault(s.parent_span_id, []).append(s)

    @property
    def total_duration_ms(self) -> float:
        if self.root_span:
            return self.root_span.duration_ms
        if self.spans:
            return max(s.duration_ms for s in self.spans)
        return 0.0

    @property
    def error_spans(self) -> List[TraceSpan]:
        return [s for s in self.spans if s.status_code == "ERROR"]

    @property
    def services_involved(self) -> List[str]:
        return sorted({s.service_id for s in self.spans})

    def find_slowest_span(self) -> Optional[TraceSpan]:
        if not self.spans:
            return None
        return max(self.spans, key=lambda s: s.duration_ms)

    def get_service_call_sequence(self) -> List[str]:
        """Return the sequence of services traversed in order of span start time."""
        sorted_spans = sorted(self.spans, key=lambda s: s.start_time)
        seq: List[str] = []
        for s in sorted_spans:
            if not seq or seq[-1] != s.service_id:
                seq.append(s.service_id)
        return seq


class TraceProcessor:
    """Indexes and analyzes distributed traces."""

    def __init__(self) -> None:
        self._traces: Dict[str, List[TraceSpan]] = {}

    def ingest_span(self, span: TraceSpan) -> None:
        self._traces.setdefault(span.trace_id, []).append(span)

    def ingest_spans(self, spans: List[TraceSpan]) -> None:
        for s in spans:
            self.ingest_span(s)

    def get_trace(self, trace_id: str) -> Optional[TraceTree]:
        spans = self._traces.get(trace_id)
        if not spans:
            return None
        return TraceTree(trace_id, spans)

    def get_all_traces(self) -> List[TraceTree]:
        return [TraceTree(tid, spans) for tid, spans in self._traces.items()]

    def find_error_traces(self) -> List[TraceTree]:
        return [t for t in self.get_all_traces() if len(t.error_spans) > 0]

