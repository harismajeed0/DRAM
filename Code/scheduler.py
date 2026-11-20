"""Request schedulers.

A scheduler looks at the request queue (oldest first) and the rank state and
returns the request it wants to serve and the DRAM command needed next for it,
or ``None`` if nothing should be issued this cycle.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .bank import Rank
from .request import Cmd, Op, Request

Choice = Optional[tuple[Request, Cmd]]


def next_command(req: Request, rank: Rank) -> Cmd:
    """The next DRAM command required to make progress on ``req``."""
    bank = rank.banks[req.bank]
    if bank.open_row == req.row:
        return Cmd.RD if req.op is Op.READ else Cmd.WR
    if bank.is_open:
        return Cmd.PRE
    return Cmd.ACT


def has_pending_hit(queue: Sequence[Request], rank: Rank, bank: int) -> bool:
    open_row = rank.banks[bank].open_row
    return open_row is not None and any(r.bank == bank and r.row == open_row for r in queue)


class Scheduler:
    name = "base"

    def pick(self, queue: Sequence[Request], rank: Rank, now: int) -> Choice:
        raise NotImplementedError


class FCFS(Scheduler):
    """Strict first-come first-served: only the oldest request may issue."""

    name = "fcfs"

    def pick(self, queue, rank, now):
        if not queue:
            return None
        req = queue[0]
        cmd = next_command(req, rank)
        if rank.can_issue(cmd, req.bank, req.row, now):
            return req, cmd
        return None


class FRFCFS(Scheduler):
    """First-ready FCFS (Rixner et al., ISCA 2000).

    1. Oldest request whose column command (a row hit) can issue now.
    2. Otherwise the oldest request whose next command can issue now.

    A bank is not precharged while queued requests still hit its open row, so
    pending hits are never thrown away by a conflicting request.
    """

    name = "frfcfs"

    def pick(self, queue, rank, now):
        for req in queue:
            cmd = next_command(req, rank)
            if cmd in (Cmd.RD, Cmd.WR) and rank.can_issue(cmd, req.bank, req.row, now):
                return req, cmd
        for req in queue:
            cmd = next_command(req, rank)
            if cmd is Cmd.PRE and has_pending_hit(queue, rank, req.bank):
                continue
            if rank.can_issue(cmd, req.bank, req.row, now):
                return req, cmd
        return None


SCHEDULERS: dict[str, type[Scheduler]] = {cls.name: cls for cls in (FCFS, FRFCFS)}


def make_scheduler(name: str) -> Scheduler:
    try:
        return SCHEDULERS[name.lower()]()
    except KeyError:
        raise ValueError(f"unknown scheduler {name!r}; choose from {', '.join(SCHEDULERS)}") from None
