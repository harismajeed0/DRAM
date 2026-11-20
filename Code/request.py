"""Memory requests and DRAM commands."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class Op(enum.Enum):
    READ = "R"
    WRITE = "W"


class Cmd(enum.Enum):
    ACT = "ACT"
    PRE = "PRE"
    RD = "RD"
    WR = "WR"
    REF = "REF"


class RowOutcome(enum.Enum):
    HIT = "hit"  # row already open
    MISS = "miss"  # bank was closed (also called "empty")
    CONFLICT = "conflict"  # a different row was open


@dataclass
class Request:
    id: int
    arrival: int
    op: Op
    address: int
    row: int = -1
    bank: int = -1
    col: int = -1
    outcome: Optional[RowOutcome] = None
    issue_cycle: Optional[int] = None  # cycle the RD/WR command was issued
    done_cycle: Optional[int] = None  # cycle the last data beat finished

    @property
    def latency(self) -> int:
        if self.done_cycle is None:
            raise ValueError(f"request {self.id} has not completed")
        return self.done_cycle - self.arrival


@dataclass(frozen=True)
class CommandRecord:
    cycle: int
    cmd: Cmd
    bank: int = -1  # -1 for rank-wide commands (REF)
    row: int = -1
    col: int = -1
    request_id: int = -1

    def to_line(self) -> str:
        return f"{self.cycle},{self.cmd.value},{self.bank},{self.row},{self.col},{self.request_id}"


@dataclass
class CommandLog:
    records: list[CommandRecord] = field(default_factory=list)

    def append(self, record: CommandRecord) -> None:
        self.records.append(record)

    def write_csv(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("cycle,cmd,bank,row,col,request_id\n")
            for record in self.records:
                fh.write(record.to_line() + "\n")

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)
