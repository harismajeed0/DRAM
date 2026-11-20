# dramlab

A cycle-level DRAM memory-controller simulator written in pure Python.

It shows how **request scheduling**, **page policy** and **address mapping** change
row-buffer hit rate, latency and bandwidth on DDR3/DDR4 devices. It enforces the
JEDEC timing rules that make DRAM behave the way it does (tRCD, tRP, tRAS, tRC,
tRRD, tFAW, tCCD, tRTP, tWR, tWTR, tRFC/tREFI) and checks every simulated command
stream with a separate timing checker.

```
$ dramlab run --pattern sequential -n 3000 --check
DDR4-2400 | scheduler=frfcfs policy=open mapping=row-bank-col
requests          3000 (2090 reads, 910 writes)
row hits          2975 (99.2%)
...
bandwidth         15.32 GB/s
timing check      OK
```

## Why

A DRAM access costs very different amounts depending on the state of the bank:

| Case | Commands | DDR4-2400 latency |
|------|----------|-------------------|
| Row hit | `RD` | tCL + tBL = 21 cycles |
| Row miss (bank closed) | `ACT` → `RD` | tRCD + tCL + tBL = 38 cycles |
| Row conflict (other row open) | `PRE` → `ACT` → `RD` | up to tRAS + tRP + tRCD + tCL + tBL |

The memory controller decides which request goes next, when to close rows, and
how physical addresses map onto banks and rows. dramlab lets you change those
choices and see the effect.

## Install

```bash
git clone https://github.com/<your-username>/dramlab.git
cd dramlab
pip install -e ".[dev]"     # or just run with: python -m dramlab ...
```

Requires Python 3.10+. There are no runtime dependencies.

## Usage

```bash
# one configuration, synthetic workload, verify timing
dramlab run --pattern random -n 3000 --scheduler frfcfs --policy open --check

# sweep schedulers x page policies x address mappings
dramlab compare --pattern sequential -n 3000 --mappings row-bank-col row-col-bank

# write a trace, then replay it
dramlab gen hotspot examples/hotspot.trace -n 500
dramlab run --trace examples/hotspot.trace --log-commands cmds.csv

# DDR3 preset, or your own JSON config
dramlab run --config ddr3-1600 --pattern strided --stride 8192
```

**Trace format.** Each line is `<arrival_cycle> <R|W> <address>`. Addresses can be hex or decimal, and `#` starts a comment.

**Options**

| Flag | Values |
|------|--------|
| `--scheduler` | `fcfs` (strict in-order), `frfcfs` (row hits first, Rixner et al. ISCA 2000) |
| `--policy` | `open` (leave rows open), `close` (precharge a bank when no queued request needs its row) |
| `--mapping` | `row-bank-col`, `row-col-bank`, `bank-row-col`, add `+xor` for permutation-based bank interleaving |
| `--config` | `ddr4-2400`, `ddr3-1600`, or a JSON file (see `DRAMConfig.to_dict()`) |
| `--pattern` | `random`, `sequential`, `strided`, `hotspot` |

## Sample results (DDR4-2400, 3000 requests, 70 % reads, one request every 5 cycles)

Sequential stream:

```
scheduler policy mapping             hit%  avg lat  p95 rd   GB/s   cycles
frfcfs    open   row-bank-col       99.2%    111.7   391.5  15.32    15046
frfcfs    open   row-col-bank       98.4%    115.8   403.0  15.29    15079
fcfs      open   row-bank-col       99.1%   5761.0 11066.5   8.59    26824
fcfs      open   row-col-bank       97.9%   6055.2 11706.5   8.39    27457
```

Uniform random:

```
scheduler policy mapping             hit%  avg lat  p95 rd   GB/s   cycles
frfcfs    open   row-col-bank        0.1%   2835.6  5776.7  10.93    21083
frfcfs    open   row-bank-col        0.0%   2942.9  5926.8  10.77    21394
fcfs      close  row-bank-col        0.0%  27179.1 52481.1   3.30    69861
fcfs      open   row-bank-col        0.0%  48322.6 92303.0   2.06   111846
```

What these show:

* **FR-FCFS nearly doubles streaming bandwidth.** Even with a 99 % row-hit rate, strict FCFS
  pays the write→read turnaround (tCWL + tBL + tWTR) on every R/W switch. FR-FCFS
  serves whichever hit is ready, which batches writes as a side effect.
* **For random traffic, close-page beats open-page under FCFS.** Almost every access
  is a conflict, so precharging early takes tRP off the critical path.
* **Random traffic is limited by tFAW, not the data bus.** At most 4 ACTs fit in 26 cycles,
  so random accesses top out near one per 6.5 cycles (about 11 GB/s here),
  well below the 19.2 GB/s peak.

## Design

```
dramlab/
├── config.py      Timing + Organization dataclasses, DDR4-2400 / DDR3-1600 presets, JSON loading
├── address.py     physical address -> (row, bank, column) for any field order, optional XOR hashing
├── request.py     Request, DRAM commands, command log
├── bank.py        per-bank + rank-level timing state; the only place commands change state
├── scheduler.py   FCFS and FR-FCFS
├── controller.py  cycle loop: arrivals, refresh, scheduling, page policy, idle-time skipping
├── checker.py     independent re-check of every timing rule from the command log alone
├── stats.py       hit/miss/conflict, latency percentiles, bandwidth, command counts
├── trace.py       trace parsing and synthetic workloads
└── cli.py         `dramlab run | compare | gen`
```

Modelling assumptions in v0.1: one channel and one rank, no bank groups (DDR4
`_S` timings), all-bank refresh, and one command per cycle on the command bus.
Read latency runs from arrival to the last data beat.

## Testing

```bash
pytest
```

The tests include hand-computed latencies (miss = 38 cycles, conflict = 94 cycles
on DDR4-2400) and scheduler-ordering cases. A property-style sweep runs every
scheduler × policy × mapping × workload × device through the independent timing
checker. The checker also has its own negative tests to show it really catches
violations.

## Roadmap

- [ ] DDR4 bank groups (tCCD_L / tRRD_L / tWTR_L)
- [ ] Multiple ranks and channels, with rank-to-rank switching delay
- [ ] Write queue with high/low watermarks (write draining)
- [ ] FR-FCFS starvation cap, BLISS / ATLAS-style schedulers
- [ ] Per-bank refresh (DDR4 FGR / LPDDR4 REFpb)
- [ ] Power model based on IDD currents (Micron power calculator method)
- [ ] Plots: latency CDF, bandwidth vs. injection rate
- [ ] Read Ramulator / DRAMSim3 trace formats and cross-check results

## License

MIT
