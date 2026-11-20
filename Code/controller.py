"""Cycle-level memory controller for one channel with one rank."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from .address import AddressMapper
from .bank import Rank
from .config import DRAMConfig
from .request import Cmd, CommandLog, CommandRecord, Op, Request, RowOutcome
from .scheduler import Scheduler, has_pending_hit, make_scheduler
from .stats import Stats

PAGE_POLICIES = ("open", "close")

_OUTCOME_FOR_FIRST_CMD = {
    Cmd.RD: RowOutcome.HIT,
    Cmd.WR: RowOutcome.HIT,
    Cmd.ACT: RowOutcome.MISS,
    Cmd.PRE: RowOutcome.CONFLICT,
}


@dataclass
class SimResult:
    stats: Stats
    requests: list[Request]
    commands: CommandLog


class MemoryController:
    def __init__(
        self,
        config: DRAMConfig,
        scheduler: str | Scheduler = "frfcfs",
        page_policy: str = "open",
        mapping: str = "row-bank-col",
        refresh: bool = True,
    ):
        if page_policy not in PAGE_POLICIES:
            raise ValueError(f"page_policy must be one of {PAGE_POLICIES}")
        self.config = config.validate()
        self.scheduler = make_scheduler(scheduler) if isinstance(scheduler, str) else scheduler
        self.page_policy = page_policy
        self.mapper = AddressMapper(config.org, mapping)
        self.refresh = refresh

    def run(self, trace: Iterable[tuple[int, Op, int]]) -> SimResult:
        """Simulate a trace of ``(arrival_cycle, op, address)`` tuples."""
        t = self.config.timing
        rank = Rank(t, self.config.org.banks)
        log = CommandLog()

        pending: deque[Request] = deque()
        for i, (arrival, op, address) in enumerate(sorted(trace, key=lambda x: x[0])):
            req = Request(id=i, arrival=arrival, op=op, address=address)
            d = self.mapper.decode(address)
            req.row, req.bank, req.col = d.row, d.bank, d.col
            pending.append(req)

        queue: list[Request] = []
        done: list[Request] = []
        now = 0
        next_refresh = t.tREFI
        refresh_due = False

        def issue(cmd: Cmd, bank: int = -1, row: int = -1, req: Request | None = None) -> None:
            rank.issue(cmd, bank, row, now)
            log.append(
                CommandRecord(
                    cycle=now, cmd=cmd, bank=bank, row=row,
                    col=req.col if req and cmd in (Cmd.RD, Cmd.WR) else -1,
                    request_id=req.id if req else -1,
                )
            )

        def busy() -> bool:
            if pending or queue:
                return True
            # Under close-page, keep going until every bank is precharged.
            return self.page_policy == "close" and any(b.is_open for b in rank.banks)

        while busy():
            while pending and pending[0].arrival <= now and len(queue) < self.config.queue_size:
                queue.append(pending.popleft())

            if self.refresh and now >= next_refresh:
                refresh_due = True

            if refresh_due:
                # Close every bank, then refresh the whole rank.
                if rank.can_issue(Cmd.REF, -1, -1, now):
                    issue(Cmd.REF)
                    refresh_due = False
                    next_refresh += t.tREFI
                else:
                    for b in rank.banks:
                        if rank.can_issue(Cmd.PRE, b.index, -1, now):
                            issue(Cmd.PRE, b.index)
                            break
            else:
                choice = self.scheduler.pick(queue, rank, now)
                if choice is not None:
                    req, cmd = choice
                    if req.outcome is None:
                        req.outcome = _OUTCOME_FOR_FIRST_CMD[cmd]
                    row = -1 if cmd is Cmd.PRE else req.row
                    issue(cmd, req.bank, row, req)
                    if cmd in (Cmd.RD, Cmd.WR):
                        lat = t.tCL if cmd is Cmd.RD else t.tCWL
                        req.issue_cycle = now
                        req.done_cycle = now + lat + t.tBL
                        queue.remove(req)
                        done.append(req)
                elif self.page_policy == "close":
                    # Close-page: precharge idle banks that no queued request needs.
                    for b in rank.banks:
                        if (
                            b.is_open
                            and not has_pending_hit(queue, rank, b.index)
                            and rank.can_issue(Cmd.PRE, b.index, -1, now)
                        ):
                            issue(Cmd.PRE, b.index)
                            break

            # Skip idle time when nothing can happen until the next arrival.
            idle = (
                not queue
                and not refresh_due
                and pending
                and (self.page_policy == "open" or not any(b.is_open for b in rank.banks))
            )
            if idle:
                target = pending[0].arrival
                if self.refresh:
                    target = min(target, next_refresh)
                now = max(now + 1, target)
            else:
                now += 1

        total = max([r.done_cycle for r in done] + [now])
        done.sort(key=lambda r: r.id)
        return SimResult(Stats.collect(self.config, done, log, total), done, log)
