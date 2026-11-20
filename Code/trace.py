"""Trace files and synthetic workload generators.

Trace format: one request per line, ``<arrival_cycle> <R|W> <address>``.
Addresses may be hex (``0x1f40``) or decimal. ``#`` starts a comment.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable

from .request import Op

TraceEntry = tuple[int, Op, int]


def parse_trace(lines: Iterable[str]) -> list[TraceEntry]:
    entries: list[TraceEntry] = []
    for lineno, raw in enumerate(lines, start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"line {lineno}: expected '<cycle> <R|W> <address>', got {raw.strip()!r}")
        cycle_s, op_s, addr_s = parts
        try:
            cycle = int(cycle_s)
            address = int(addr_s, 0)
            op = Op(op_s.upper())
        except ValueError:
            raise ValueError(f"line {lineno}: could not parse {raw.strip()!r}") from None
        if cycle < 0 or address < 0:
            raise ValueError(f"line {lineno}: cycle and address must be non-negative")
        entries.append((cycle, op, address))
    return entries


def load_trace(path: str | Path) -> list[TraceEntry]:
    with open(path, encoding="utf-8") as fh:
        return parse_trace(fh)


def save_trace(entries: Iterable[TraceEntry], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# cycle op address\n")
        for cycle, op, address in entries:
            fh.write(f"{cycle} {op.value} {address:#x}\n")


def _op(rng: random.Random, read_ratio: float) -> Op:
    return Op.READ if rng.random() < read_ratio else Op.WRITE


def sequential(n: int, interval: int = 2, read_ratio: float = 1.0, start: int = 0,
               line_size: int = 64, seed: int = 0) -> list[TraceEntry]:
    """Streaming access: consecutive cache lines."""
    rng = random.Random(seed)
    return [(i * interval, _op(rng, read_ratio), start + i * line_size) for i in range(n)]


def strided(n: int, stride: int, interval: int = 2, read_ratio: float = 1.0,
            seed: int = 0) -> list[TraceEntry]:
    """Fixed-stride access, e.g. walking a column of a large matrix."""
    rng = random.Random(seed)
    return [(i * interval, _op(rng, read_ratio), i * stride) for i in range(n)]


def uniform_random(n: int, footprint: int = 1 << 30, interval: int = 2,
                   read_ratio: float = 1.0, line_size: int = 64, seed: int = 0) -> list[TraceEntry]:
    """Uniformly random cache lines inside ``footprint`` bytes."""
    rng = random.Random(seed)
    lines = footprint // line_size
    return [(i * interval, _op(rng, read_ratio), rng.randrange(lines) * line_size) for i in range(n)]


def hotspot(n: int, hot_fraction: float = 0.9, hot_bytes: int = 64 * 1024,
            footprint: int = 1 << 30, interval: int = 2, read_ratio: float = 1.0,
            line_size: int = 64, seed: int = 0) -> list[TraceEntry]:
    """Most accesses fall in a small hot region; the rest are random."""
    rng = random.Random(seed)
    entries = []
    for i in range(n):
        size = hot_bytes if rng.random() < hot_fraction else footprint
        entries.append((i * interval, _op(rng, read_ratio), rng.randrange(size // line_size) * line_size))
    return entries


PATTERNS = {
    "sequential": sequential,
    "random": uniform_random,
    "hotspot": hotspot,
}


def generate(pattern: str, n: int, interval: int = 2, read_ratio: float = 1.0,
             seed: int = 0, stride: int | None = None) -> list[TraceEntry]:
    if pattern == "strided":
        return strided(n, stride or 8192, interval=interval, read_ratio=read_ratio, seed=seed)
    try:
        fn = PATTERNS[pattern]
    except KeyError:
        names = ", ".join([*PATTERNS, "strided"])
        raise ValueError(f"unknown pattern {pattern!r}; choose from {names}") from None
    return fn(n, interval=interval, read_ratio=read_ratio, seed=seed)
