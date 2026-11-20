"""Command-line interface: ``dramlab run | compare | gen``."""

from __future__ import annotations

import argparse
import itertools
import json
import sys

from . import __version__
from .checker import check_commands
from .config import PRESETS, load_config
from .controller import PAGE_POLICIES, MemoryController
from .scheduler import SCHEDULERS
from .trace import PATTERNS, generate, load_trace, save_trace

MAPPINGS = ["row-bank-col", "row-col-bank", "bank-row-col", "row-bank-col+xor"]


def _add_workload_args(p: argparse.ArgumentParser) -> None:
    src = p.add_mutually_exclusive_group()
    src.add_argument("--trace", help="trace file (<cycle> <R|W> <address> per line)")
    src.add_argument("--pattern", default="random",
                     choices=[*PATTERNS, "strided"], help="synthetic workload (default: random)")
    p.add_argument("-n", "--num-requests", type=int, default=2000)
    p.add_argument("--interval", type=int, default=5, help="cycles between synthetic requests")
    p.add_argument("--read-ratio", type=float, default=0.7)
    p.add_argument("--stride", type=int, default=None, help="byte stride for --pattern strided")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--config", default="ddr4-2400",
                   help=f"preset ({', '.join(PRESETS)}) or path to a JSON config")
    p.add_argument("--no-refresh", action="store_true", help="disable refresh")


def _workload(args):
    if args.trace:
        return load_trace(args.trace)
    return generate(args.pattern, args.num_requests, interval=args.interval,
                    read_ratio=args.read_ratio, seed=args.seed, stride=args.stride)


def cmd_run(args) -> int:
    config = load_config(args.config)
    mc = MemoryController(config, scheduler=args.scheduler, page_policy=args.policy,
                          mapping=args.mapping, refresh=not args.no_refresh)
    result = mc.run(_workload(args))
    if args.log_commands:
        result.commands.write_csv(args.log_commands)
    errors = check_commands(result.commands, config.timing, config.org.banks) if args.check else []
    if args.json:
        out = result.stats.to_dict()
        if args.check:
            out["timing_violations"] = len(errors)
        print(json.dumps(out, indent=2))
    else:
        print(f"{config.name} | scheduler={args.scheduler} policy={args.policy} mapping={args.mapping}")
        print(result.stats.format())
        if args.check:
            print(f"timing check      {'OK' if not errors else f'{len(errors)} violations'}")
    for e in errors[:20]:
        print("  " + e, file=sys.stderr)
    return 1 if errors else 0


def cmd_compare(args) -> int:
    config = load_config(args.config)
    trace = _workload(args)
    rows = []
    for sched, policy, mapping in itertools.product(args.schedulers, args.policies, args.mappings):
        mc = MemoryController(config, scheduler=sched, page_policy=policy,
                              mapping=mapping, refresh=not args.no_refresh)
        s = mc.run(trace).stats
        rows.append((sched, policy, mapping, s))
    header = f"{'scheduler':<9} {'policy':<6} {'mapping':<17} {'hit%':>6} {'avg lat':>8} {'p95 rd':>7} {'GB/s':>6} {'cycles':>8}"
    print(f"{config.name}, {len(trace)} requests")
    print(header)
    print("-" * len(header))
    for sched, policy, mapping, s in sorted(rows, key=lambda r: r[3].total_cycles):
        print(f"{sched:<9} {policy:<6} {mapping:<17} {s.row_hit_rate*100:>5.1f}% "
              f"{s.avg_latency:>8.1f} {s.p95_read_latency:>7.1f} {s.bandwidth_gbps:>6.2f} {s.total_cycles:>8}")
    return 0


def cmd_gen(args) -> int:
    entries = generate(args.pattern, args.num_requests, interval=args.interval,
                       read_ratio=args.read_ratio, seed=args.seed, stride=args.stride)
    save_trace(entries, args.output)
    print(f"wrote {len(entries)} requests to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dramlab", description="Cycle-level DRAM controller simulator")
    parser.add_argument("--version", action="version", version=f"dramlab {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="simulate one configuration")
    _add_workload_args(run)
    run.add_argument("--scheduler", default="frfcfs", choices=list(SCHEDULERS))
    run.add_argument("--policy", default="open", choices=PAGE_POLICIES)
    run.add_argument("--mapping", default="row-bank-col",
                     help=f"address mapping, e.g. {', '.join(MAPPINGS)}")
    run.add_argument("--log-commands", metavar="CSV", help="write the DRAM command log to CSV")
    run.add_argument("--check", action="store_true", help="verify the command log against all timing rules")
    run.add_argument("--json", action="store_true", help="print stats as JSON")
    run.set_defaults(func=cmd_run)

    cmp_ = sub.add_parser("compare", help="sweep schedulers, page policies and mappings")
    _add_workload_args(cmp_)
    cmp_.add_argument("--schedulers", nargs="+", default=list(SCHEDULERS))
    cmp_.add_argument("--policies", nargs="+", default=list(PAGE_POLICIES))
    cmp_.add_argument("--mappings", nargs="+", default=MAPPINGS[:2])
    cmp_.set_defaults(func=cmd_compare)

    gen = sub.add_parser("gen", help="write a synthetic trace file")
    gen.add_argument("pattern", choices=[*PATTERNS, "strided"])
    gen.add_argument("output")
    gen.add_argument("-n", "--num-requests", type=int, default=2000)
    gen.add_argument("--interval", type=int, default=5)
    gen.add_argument("--read-ratio", type=float, default=0.7)
    gen.add_argument("--stride", type=int, default=None)
    gen.add_argument("--seed", type=int, default=1)
    gen.set_defaults(func=cmd_gen)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
