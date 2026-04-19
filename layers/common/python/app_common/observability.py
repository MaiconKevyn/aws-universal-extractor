from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any


@dataclass
class TraceSpan:
    name: str
    start_time: str
    end_time: str
    duration_ms: int
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TraceRecorder:
    def __init__(self, *, request_id: str) -> None:
        self.request_id = request_id
        self.started_at = datetime.now(UTC).isoformat()
        self._spans: list[TraceSpan] = []

    def record(self, name: str, start: float, attributes: dict[str, Any] | None = None) -> None:
        end = perf_counter()
        now = datetime.now(UTC).isoformat()
        self._spans.append(
            TraceSpan(
                name=name,
                start_time=now,
                end_time=now,
                duration_ms=int((end - start) * 1000),
                attributes=attributes or {},
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "started_at": self.started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "spans": [span.to_dict() for span in self._spans],
        }
