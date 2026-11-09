"""Time-series alignment, sampling, and missing-data handling for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable, Dict, List, Literal, Optional, Tuple
from schemas.telemetry import NormalizedMetricPoint

MissingDataStrategy = Literal["drop", "forward_fill", "linear_interpolate", "explicit_marker"]
AggregationType = Literal["mean", "max", "min", "p95", "last", "count"]


def parse_iso(ts: str) -> float:
    """Parse ISO 8601 string to UNIX epoch float in seconds."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.timestamp()


def format_iso(epoch: float) -> str:
    """Format UNIX epoch float to ISO 8601 UTC string."""
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.isoformat()


class TimeSeriesProcessor:
    """Aligns, samples, and resolves missing time-series data without inventing telemetry."""

    @staticmethod
    def aggregate_points(values: List[float], method: AggregationType = "mean") -> float:
        if not values:
            return 0.0
        if method == "mean":
            return sum(values) / len(values)
        if method == "max":
            return max(values)
        if method == "min":
            return min(values)
        if method == "p95":
            s = sorted(values)
            idx = int(math.ceil(0.95 * len(s))) - 1
            return s[max(0, idx)]
        if method == "last":
            return values[-1]
        if method == "count":
            return float(len(values))
        return sum(values) / len(values)

    @classmethod
    def resample_and_align(
        cls,
        points: List[NormalizedMetricPoint],
        bucket_seconds: float = 1.0,
        aggregation: AggregationType = "mean",
        missing_strategy: MissingDataStrategy = "drop",
    ) -> List[NormalizedMetricPoint]:
        """Align metric points into uniform time buckets with explicit missing-data handling."""
        if not points:
            return []

        # Sort points by timestamp
        sorted_points = sorted(points, key=lambda p: parse_iso(p.timestamp))
        metric_name = sorted_points[0].metric_name
        category = sorted_points[0].category
        service_id = sorted_points[0].service_id
        unit = sorted_points[0].unit

        start_epoch = math.floor(parse_iso(sorted_points[0].timestamp) / bucket_seconds) * bucket_seconds
        end_epoch = math.ceil(parse_iso(sorted_points[-1].timestamp) / bucket_seconds) * bucket_seconds

        # Group points into buckets
        buckets: Dict[float, List[float]] = {}
        for p in sorted_points:
            t = parse_iso(p.timestamp)
            b = math.floor((t - start_epoch) / bucket_seconds) * bucket_seconds + start_epoch
            buckets.setdefault(b, []).append(p.value)

        # Generate continuous grid of buckets from start to end
        current_epoch = start_epoch
        grid_epochs: List[float] = []
        while current_epoch <= end_epoch:
            grid_epochs.append(current_epoch)
            current_epoch += bucket_seconds

        aligned_points: List[NormalizedMetricPoint] = []
        last_valid_value: Optional[float] = None

        for idx, epoch in enumerate(grid_epochs):
            ts_str = format_iso(epoch)
            vals = buckets.get(epoch)

            if vals is not None and len(vals) > 0:
                agg_val = cls.aggregate_points(vals, aggregation)
                last_valid_value = agg_val
                aligned_points.append(
                    NormalizedMetricPoint(
                        metric_name=metric_name,
                        category=category,
                        service_id=service_id,
                        timestamp=ts_str,
                        value=round(agg_val, 4),
                        unit=unit,
                        imputed=False,
                        missing=False,
                    )
                )
            else:
                # Missing bucket
                if missing_strategy == "drop":
                    continue
                elif missing_strategy == "explicit_marker":
                    aligned_points.append(
                        NormalizedMetricPoint(
                            metric_name=metric_name,
                            category=category,
                            service_id=service_id,
                            timestamp=ts_str,
                            value=float("nan"),
                            unit=unit,
                            imputed=False,
                            missing=True,
                        )
                    )
                elif missing_strategy == "forward_fill":
                    if last_valid_value is not None:
                        aligned_points.append(
                            NormalizedMetricPoint(
                                metric_name=metric_name,
                                category=category,
                                service_id=service_id,
                                timestamp=ts_str,
                                value=round(last_valid_value, 4),
                                unit=unit,
                                imputed=True,
                                missing=False,
                            )
                        )
                elif missing_strategy == "linear_interpolate":
                    # Look ahead for next valid bucket
                    next_val: Optional[float] = None
                    next_dist = 0
                    for f_idx in range(idx + 1, len(grid_epochs)):
                        f_epoch = grid_epochs[f_idx]
                        if f_epoch in buckets and buckets[f_epoch]:
                            next_val = cls.aggregate_points(buckets[f_epoch], aggregation)
                            next_dist = f_idx - idx
                            break

                    if last_valid_value is not None and next_val is not None and next_dist > 0:
                        step = (next_val - last_valid_value) / (next_dist + 1)
                        interp_val = last_valid_value + step
                        last_valid_value = interp_val
                        aligned_points.append(
                            NormalizedMetricPoint(
                                metric_name=metric_name,
                                category=category,
                                service_id=service_id,
                                timestamp=ts_str,
                                value=round(interp_val, 4),
                                unit=unit,
                                imputed=True,
                                missing=False,
                            )
                        )
                    elif last_valid_value is not None:
                        # Fallback to forward fill at boundary
                        aligned_points.append(
                            NormalizedMetricPoint(
                                metric_name=metric_name,
                                category=category,
                                service_id=service_id,
                                timestamp=ts_str,
                                value=round(last_valid_value, 4),
                                unit=unit,
                                imputed=True,
                                missing=False,
                            )
                        )

        return aligned_points
