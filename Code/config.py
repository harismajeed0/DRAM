"""DRAM device timing and organization parameters.

All timing values are in memory-clock cycles (tCK) unless stated otherwise.
Presets are simplified single-rank, single-channel models: bank groups are
ignored (the "short" variants tCCD_S / tRRD_S / tWTR_S are used).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class Timing:
    tCK_ns: float  # clock period in nanoseconds
    tCL: int  # READ to first data
    tCWL: int  # WRITE to first data
    tRCD: int  # ACT to READ/WRITE (same bank)
    tRP: int  # PRE to ACT (same bank)
    tRAS: int  # ACT to PRE (same bank)
    tRC: int  # ACT to ACT (same bank)
    tBL: int  # data burst length on the bus (BL8 -> 4 cycles, DDR)
    tCCD: int  # column command to column command
    tRRD: int  # ACT to ACT (different banks)
    tFAW: int  # rolling window that may contain at most four ACTs
    tRTP: int  # READ to PRE (same bank)
    tWR: int  # write recovery: end of write data to PRE
    tWTR: int  # end of write data to READ
    tRFC: int  # REF to any ACT
    tREFI: int  # average interval between REF commands

    def validate(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if value <= 0:
                raise ValueError(f"timing parameter {f.name} must be positive, got {value}")
        if self.tRC < self.tRAS + self.tRP:
            raise ValueError("tRC must be >= tRAS + tRP")
        if self.tREFI <= self.tRFC:
            raise ValueError("tREFI must be larger than tRFC")


@dataclass(frozen=True)
class Organization:
    banks: int  # banks per rank
    rows: int  # rows per bank
    row_size_bytes: int  # bytes in one open row across the whole rank
    line_size_bytes: int = 64  # bytes moved by one READ/WRITE burst

    @property
    def lines_per_row(self) -> int:
        return self.row_size_bytes // self.line_size_bytes

    @property
    def capacity_bytes(self) -> int:
        return self.banks * self.rows * self.row_size_bytes

    def validate(self) -> None:
        for name in ("banks", "rows", "row_size_bytes", "line_size_bytes"):
            value = getattr(self, name)
            if value <= 0 or value & (value - 1):
                raise ValueError(f"{name} must be a positive power of two, got {value}")
        if self.row_size_bytes < self.line_size_bytes:
            raise ValueError("row_size_bytes must be >= line_size_bytes")


@dataclass(frozen=True)
class DRAMConfig:
    name: str
    timing: Timing
    org: Organization
    queue_size: int = 32
    extra: dict = field(default_factory=dict)

    def validate(self) -> "DRAMConfig":
        self.timing.validate()
        self.org.validate()
        if self.queue_size <= 0:
            raise ValueError("queue_size must be positive")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DRAMConfig":
        return cls(
            name=data.get("name", "custom"),
            timing=Timing(**data["timing"]),
            org=Organization(**data["org"]),
            queue_size=data.get("queue_size", 32),
            extra=data.get("extra", {}),
        ).validate()

    @classmethod
    def from_json(cls, path: str | Path) -> "DRAMConfig":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


# DDR4-2400 (17-17-17), 8 Gb x8 devices, one rank of 8 chips.
DDR4_2400 = DRAMConfig(
    name="DDR4-2400",
    timing=Timing(
        tCK_ns=0.833, tCL=17, tCWL=12, tRCD=17, tRP=17, tRAS=39, tRC=56,
        tBL=4, tCCD=4, tRRD=4, tFAW=26, tRTP=9, tWR=18, tWTR=3,
        tRFC=420, tREFI=9360,
    ),
    org=Organization(banks=16, rows=65536, row_size_bytes=8192),
).validate()

# DDR3-1600 (11-11-11), 4 Gb x8 devices, one rank of 8 chips.
DDR3_1600 = DRAMConfig(
    name="DDR3-1600",
    timing=Timing(
        tCK_ns=1.25, tCL=11, tCWL=8, tRCD=11, tRP=11, tRAS=28, tRC=39,
        tBL=4, tCCD=4, tRRD=5, tFAW=24, tRTP=6, tWR=12, tWTR=6,
        tRFC=208, tREFI=6240,
    ),
    org=Organization(banks=8, rows=65536, row_size_bytes=8192),
).validate()

PRESETS: dict[str, DRAMConfig] = {
    "ddr4-2400": DDR4_2400,
    "ddr3-1600": DDR3_1600,
}


def load_config(name_or_path: str) -> DRAMConfig:
    """Return a preset by name, or load a JSON config file."""
    key = name_or_path.lower()
    if key in PRESETS:
        return PRESETS[key]
    path = Path(name_or_path)
    if path.exists():
        return DRAMConfig.from_json(path)
    raise ValueError(
        f"unknown config {name_or_path!r}; presets: {', '.join(sorted(PRESETS))}"
    )
