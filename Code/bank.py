"""Per-bank and rank-level timing state."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .config import Timing
from .request import Cmd


@dataclass
class Bank:
    index: int
    open_row: Optional[int] = None
    next_act: int = 0
    next_pre: int = 0
    next_rd: int = 0
    next_wr: int = 0

    @property
    def is_open(self) -> bool:
        return self.open_row is not None


@dataclass
class Rank:
    """Timing state shared by all banks of one rank (single command/data bus)."""

    timing: Timing
    num_banks: int
    banks: list[Bank] = field(init=False)
    next_act: int = 0  # tRRD
    next_rd: int = 0  # tCCD and write-to-read turnaround
    next_wr: int = 0  # tCCD and read-to-write turnaround
    act_window: deque = field(default_factory=lambda: deque(maxlen=4))  # tFAW
    last_cmd_cycle: int = -1  # one command per cycle on the command bus

    def __post_init__(self) -> None:
        self.banks = [Bank(i) for i in range(self.num_banks)]

    # -- readiness checks -------------------------------------------------
    def bus_free(self, now: int) -> bool:
        return now > self.last_cmd_cycle

    def can_act(self, bank: int, now: int) -> bool:
        b = self.banks[bank]
        if b.is_open or now < b.next_act or now < self.next_act:
            return False
        if len(self.act_window) == 4 and now < self.act_window[0] + self.timing.tFAW:
            return False
        return True

    def can_pre(self, bank: int, now: int) -> bool:
        b = self.banks[bank]
        return b.is_open and now >= b.next_pre

    def can_rd(self, bank: int, row: int, now: int) -> bool:
        b = self.banks[bank]
        return b.open_row == row and now >= b.next_rd and now >= self.next_rd

    def can_wr(self, bank: int, row: int, now: int) -> bool:
        b = self.banks[bank]
        return b.open_row == row and now >= b.next_wr and now >= self.next_wr

    def can_ref(self, now: int) -> bool:
        return all(not b.is_open and now >= b.next_act for b in self.banks)

    def can_issue(self, cmd: Cmd, bank: int, row: int, now: int) -> bool:
        if not self.bus_free(now):
            return False
        if cmd is Cmd.ACT:
            return self.can_act(bank, now)
        if cmd is Cmd.PRE:
            return self.can_pre(bank, now)
        if cmd is Cmd.RD:
            return self.can_rd(bank, row, now)
        if cmd is Cmd.WR:
            return self.can_wr(bank, row, now)
        if cmd is Cmd.REF:
            return self.can_ref(now)
        raise ValueError(cmd)

    # -- state updates ----------------------------------------------------
    def issue(self, cmd: Cmd, bank: int, row: int, now: int) -> None:
        if not self.can_issue(cmd, bank, row, now):
            raise RuntimeError(f"timing violation: {cmd.value} bank={bank} row={row} at {now}")
        t = self.timing
        self.last_cmd_cycle = now
        if cmd is Cmd.ACT:
            b = self.banks[bank]
            b.open_row = row
            b.next_rd = max(b.next_rd, now + t.tRCD)
            b.next_wr = max(b.next_wr, now + t.tRCD)
            b.next_pre = max(b.next_pre, now + t.tRAS)
            b.next_act = max(b.next_act, now + t.tRC)
            self.next_act = max(self.next_act, now + t.tRRD)
            self.act_window.append(now)
        elif cmd is Cmd.PRE:
            b = self.banks[bank]
            b.open_row = None
            b.next_act = max(b.next_act, now + t.tRP)
        elif cmd is Cmd.RD:
            b = self.banks[bank]
            self.next_rd = max(self.next_rd, now + t.tCCD)
            # read-to-write bus turnaround (+2 cycles of bus idle)
            self.next_wr = max(self.next_wr, now + t.tCL + t.tBL + 2 - t.tCWL)
            b.next_pre = max(b.next_pre, now + t.tRTP)
        elif cmd is Cmd.WR:
            b = self.banks[bank]
            self.next_wr = max(self.next_wr, now + t.tCCD)
            self.next_rd = max(self.next_rd, now + t.tCWL + t.tBL + t.tWTR)
            b.next_pre = max(b.next_pre, now + t.tCWL + t.tBL + t.tWR)
        elif cmd is Cmd.REF:
            for b in self.banks:
                b.next_act = max(b.next_act, now + t.tRFC)
