"""Independent timing checker for command logs.

The checker re-derives every JEDEC-style constraint from the command history
alone, without using the controller's own bookkeeping, so it catches bugs in
:mod:`dramlab.bank`. It is used by the test-suite and by ``dramlab run --check``.
"""

from __future__ import annotations

from typing import Iterable

from .config import Timing
from .request import Cmd, CommandRecord

NEVER = -(10**12)


def check_commands(records: Iterable[CommandRecord], timing: Timing, num_banks: int) -> list[str]:
    t = timing
    errors: list[str] = []
    open_row = [None] * num_banks
    last_act = [NEVER] * num_banks
    last_pre = [NEVER] * num_banks
    last_rd = [NEVER] * num_banks
    last_wr = [NEVER] * num_banks
    acts: list[int] = []
    last_rd_any = last_wr_any = last_ref = NEVER
    prev_cycle = NEVER

    def need(cond: bool, rec: CommandRecord, msg: str) -> None:
        if not cond:
            errors.append(f"cycle {rec.cycle}: {rec.cmd.value} bank {rec.bank}: {msg}")

    for rec in records:
        now, b = rec.cycle, rec.bank
        need(now > prev_cycle, rec, "more than one command in a cycle")
        prev_cycle = now

        if rec.cmd is Cmd.ACT:
            need(open_row[b] is None, rec, "bank already open")
            need(now - last_pre[b] >= t.tRP, rec, "tRP")
            need(now - last_act[b] >= t.tRC, rec, "tRC")
            need(not acts or now - acts[-1] >= t.tRRD, rec, "tRRD")
            need(len(acts) < 4 or now - acts[-4] >= t.tFAW, rec, "tFAW")
            need(now - last_ref >= t.tRFC, rec, "tRFC")
            open_row[b] = rec.row
            last_act[b] = now
            acts.append(now)
        elif rec.cmd is Cmd.PRE:
            need(open_row[b] is not None, rec, "bank not open")
            need(now - last_act[b] >= t.tRAS, rec, "tRAS")
            need(now - last_rd[b] >= t.tRTP, rec, "tRTP")
            need(now - last_wr[b] >= t.tCWL + t.tBL + t.tWR, rec, "tWR")
            open_row[b] = None
            last_pre[b] = now
        elif rec.cmd in (Cmd.RD, Cmd.WR):
            need(open_row[b] is not None and open_row[b] == rec.row, rec, "row not open")
            need(now - last_act[b] >= t.tRCD, rec, "tRCD")
            need(now - max(last_rd_any, last_wr_any) >= t.tCCD, rec, "tCCD")
            if rec.cmd is Cmd.RD:
                need(now - last_wr_any >= t.tCWL + t.tBL + t.tWTR, rec, "tWTR")
                last_rd[b] = last_rd_any = now
            else:
                need(now - last_rd_any >= t.tCL + t.tBL + 2 - t.tCWL, rec, "read-to-write turnaround")
                last_wr[b] = last_wr_any = now
        elif rec.cmd is Cmd.REF:
            need(all(r is None for r in open_row), rec, "banks not all precharged")
            need(now - max(last_pre) >= t.tRP, rec, "tRP before REF")
            need(now - max(last_act) >= t.tRC, rec, "tRC before REF")
            need(now - last_ref >= t.tRFC, rec, "tRFC between REFs")
            last_ref = now
    return errors
