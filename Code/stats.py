"""Summary statistics for a simulation run."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Iterable

from .config import DRAMConfig
from .request import CommandLog, Op, Request, RowOutcome


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


@dataclass
class Stats:
    requests: int = 0
    reads: int = 0
    writes: int = 0
    row_hits: int = 0
    row_misses: int = 0
    row_conflicts: int = 0
    total_cycles: int = 0
    avg_latency: float = 0.0
    avg_read_latency: float = 0.0
    p95_read_latency: float = 0.0
    max_latency: int = 0
    bandwidth_gbps: float = 0.0
    bus_utilization: float = 0.0
    commands: dict = field(default_factory=dict)

    @property
    def row_hit_rate(self) -> float:
        return self.row_hits / self.requests if self.requests else 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["row_hit_rate"] = round(self.row_hit_rate, 4)
        return data

    @classmethod
    def collect(
        cls, config: DRAMConfig, requests: Iterable[Request], log: CommandLog, total_cycles: int
    ) -> "Stats":
        reqs = list(requests)
        latencies = [r.latency for r in reqs]
        read_lat = [r.latency for r in reqs if r.op is Op.READ]
        outcomes = Counter(r.outcome for r in reqs)
        t = config.timing
        bytes_moved = len(reqs) * config.org.line_size_bytes
        seconds = total_cycles * t.tCK_ns * 1e-9
        return cls(
            requests=len(reqs),
            reads=len(read_lat),
            writes=len(reqs) - len(read_lat),
            row_hits=outcomes[RowOutcome.HIT],
            row_misses=outcomes[RowOutcome.MISS],
            row_conflicts=outcomes[RowOutcome.CONFLICT],
            total_cycles=total_cycles,
            avg_latency=sum(latencies) / len(latencies) if latencies else 0.0,
            avg_read_latency=sum(read_lat) / len(read_lat) if read_lat else 0.0,
            p95_read_latency=percentile(read_lat, 95),
            max_latency=max(latencies, default=0),
            bandwidth_gbps=bytes_moved / seconds / 1e9 if seconds else 0.0,
            bus_utilization=len(reqs) * t.tBL / total_cycles if total_cycles else 0.0,
            commands=dict(Counter(rec.cmd.value for rec in log)),
        )

    def format(self) -> str:
        lines = [
            f"requests          {self.requests} ({self.reads} reads, {self.writes} writes)",
            f"row hits          {self.row_hits} ({self.row_hit_rate:.1%})",
            f"row misses        {self.row_misses}",
            f"row conflicts     {self.row_conflicts}",
            f"total cycles      {self.total_cycles}",
            f"avg latency       {self.avg_latency:.1f} cycles",
            f"avg read latency  {self.avg_read_latency:.1f} cycles",
            f"p95 read latency  {self.p95_read_latency:.1f} cycles",
            f"max latency       {self.max_latency} cycles",
            f"bandwidth         {self.bandwidth_gbps:.2f} GB/s",
            f"data bus util.    {self.bus_utilization:.1%}",
            "commands          "
            + ", ".join(f"{k}={v}" for k, v in sorted(self.commands.items())),
        ]
        return "\n".join(lines)
