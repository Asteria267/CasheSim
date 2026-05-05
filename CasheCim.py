#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║         CPU CACHE HIERARCHY SIMULATOR  ·  v1.0                  ║
║         L1 + L2 · LRU Eviction · Cortex-M Cycle Model           ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
    python cache_sim.py                          # interactive menu
    python cache_sim.py --preset thrash          # run a preset
    python cache_sim.py --seq "0 1 2 3 0 1 4"   # custom sequence
    python cache_sim.py --l1 8 --l2 16 --seq "0 1 2 3 0 1"
    python cache_sim.py --list-presets

Requirements:
    pip install rich numpy
"""

import time
import argparse
import textwrap
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

import numpy as np
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ─────────────────────────────────────────────────────────────────
#  Theme & constants
# ─────────────────────────────────────────────────────────────────

THEME = Theme({
    "l1":    "bold green",
    "l2":    "bold dark_orange",
    "miss":  "bold red",
    "evict": "bold orange1",
    "dim":   "grey50",
    "head":  "bold white",
    "addr":  "cyan",
    "label": "grey70",
    "border":"grey30",
})

console = Console(theme=THEME)

CYCLES = {"l1": 2, "l2": 10, "miss": 100}

_STYLE  = {"l1": "l1",  "l2": "l2",  "miss": "miss",  "evict": "evict"}
_SYMBOL = {"l1": "█",   "l2": "▓",   "miss": "░",     "evict": "▒"}

PRESETS: dict[str, list[int]] = {
    "temporal":   [0,1,2,3,0,1,2,3,0,1,2,3,0,1,2,3],
    "sequential": list(range(20)),
    "thrash":     [0,4,8,12,0,4,8,12,0,4,8,12,0,4,8,12],
    "mixed":      [0,1,2,3,0,1,4,0,1,2,3,4,5,0,1,0,2,3,6,7,0,1,2,0,5,6,0,1],
    "hot_data":   [0,0,0,1,0,1,2,0,1,0,2,1,0,3,0,1,0],
    "stride2":    [i for i in range(0, 32, 2)],
    "working_set":[0,1,2,3,4,0,1,2,3,4,5,6,0,1,2,3,4,5,6,7,0,1,2],
}

PRESET_DESC = {
    "temporal":    "Same addresses repeated — high L1 rate",
    "sequential":  "Linear scan — spatial locality only",
    "thrash":      "Stride = cache size — constant evictions",
    "mixed":       "Realistic firmware-style access pattern",
    "hot_data":    "One hot address dominates — near-100% L1",
    "stride2":     "Skip-2 stride — moderate locality",
    "working_set": "Growing working set — watch L1 degrade",
}


# ─────────────────────────────────────────────────────────────────
#  Data model
# ─────────────────────────────────────────────────────────────────

@dataclass
class AccessResult:
    addr:     int
    tick:     int
    kind:     str
    l1_evict: Optional[int] = None
    l2_evict: Optional[int] = None

    @property
    def cycles(self) -> int:
        return CYCLES[self.kind]

    @property
    def display_kind(self) -> str:
        if self.kind in ("l2", "miss") and (self.l1_evict is not None or self.l2_evict is not None):
            return "evict"
        return self.kind

    @property
    def kind_label(self) -> str:
        return {"l1": "L1 hit", "l2": "L2 hit", "miss": "MISS  "}[self.kind]


@dataclass
class SimStats:
    l1_hits: int = 0
    l2_hits: int = 0
    misses:  int = 0

    @property
    def total(self) -> int:
        return self.l1_hits + self.l2_hits + self.misses

    @property
    def l1_rate(self) -> float:
        return self.l1_hits / self.total if self.total else 0.0

    @property
    def l2_rate(self) -> float:
        return self.l2_hits / self.total if self.total else 0.0

    @property
    def miss_rate(self) -> float:
        return self.misses / self.total if self.total else 0.0

    @property
    def total_cycles(self) -> int:
        return self.l1_hits * CYCLES["l1"] + self.l2_hits * CYCLES["l2"] + self.misses * CYCLES["miss"]

    @property
    def avg_cycles(self) -> float:
        return self.total_cycles / self.total if self.total else 0.0

    @property
    def cycle_penalty(self) -> int:
        return self.total_cycles - self.total * CYCLES["l1"]


# ─────────────────────────────────────────────────────────────────
#  LRU cache
# ─────────────────────────────────────────────────────────────────

class LRUCache:
    def __init__(self, size: int, name: str):
        self.size   = size
        self.name   = name
        self._store: OrderedDict[int, int] = OrderedDict()

    def __contains__(self, addr: int) -> bool:
        return addr in self._store

    def __len__(self) -> int:
        return len(self._store)

    def touch(self, addr: int, tick: int) -> None:
        self._store.move_to_end(addr)
        self._store[addr] = tick

    def insert(self, addr: int, tick: int) -> Optional[int]:
        evicted = None
        if len(self._store) >= self.size:
            evicted, _ = self._store.popitem(last=False)
        self._store[addr] = tick
        return evicted

    def contents_mru_first(self) -> list[tuple[int, int]]:
        return list(reversed(self._store.items()))


# ─────────────────────────────────────────────────────────────────
#  Simulator
# ─────────────────────────────────────────────────────────────────

class CacheSimulator:
    def __init__(self, l1_size: int = 4, l2_size: int = 8):
        self.l1      = LRUCache(l1_size, "L1")
        self.l2      = LRUCache(l2_size, "L2")
        self._tick   = 0
        self.stats   = SimStats()
        self.results: list[AccessResult] = []

    def access(self, addr: int) -> AccessResult:
        self._tick += 1
        t = self._tick
        r = AccessResult(addr=addr, tick=t, kind="miss")

        if addr in self.l1:
            self.l1.touch(addr, t)
            r.kind = "l1"
            self.stats.l1_hits += 1
        elif addr in self.l2:
            self.l2.touch(addr, t)
            r.kind     = "l2"
            r.l1_evict = self.l1.insert(addr, t)
            self.stats.l2_hits += 1
        else:
            r.l2_evict = self.l2.insert(addr, t)
            r.l1_evict = self.l1.insert(addr, t)
            self.stats.misses += 1

        self.results.append(r)
        return r


# ─────────────────────────────────────────────────────────────────
#  Render helpers
# ─────────────────────────────────────────────────────────────────

def _bar(rate: float, color: str, width: int = 22) -> Text:
    filled = round(rate * width)
    t = Text()
    t.append("█" * filled,           style=color)
    t.append("░" * (width - filled),  style="dim")
    t.append(f"  {rate*100:5.1f}%",   style=color)
    return t


def make_header() -> Panel:
    t = Text(justify="center")
    t.append("CPU CACHE HIERARCHY SIMULATOR", style="bold bright_white")
    t.append("  ·  ", style="dim")
    t.append("L1 + L2", style="l1")
    t.append(" · ", style="dim")
    t.append("LRU eviction", style="l2")
    t.append(" · ", style="dim")
    t.append("Cortex-M cycle model", style="dim")
    return Panel(t, border_style="border", padding=(0, 2))


def make_legend() -> Text:
    t = Text()
    for kind, label in [("l1","L1 hit"),("l2","L2 hit"),("miss","miss"),("evict","eviction")]:
        t.append(f"  {_SYMBOL[kind]} {label}", style=_STYLE[kind])
    return t


def make_grid(results: list[AccessResult], cols: int = 16) -> Panel:
    rows: list[Text] = []
    row = Text()
    for i, r in enumerate(results):
        if i > 0 and i % cols == 0:
            rows.append(row)
            row = Text()
        dk = r.display_kind
        row.append(f"{_SYMBOL[dk]}{r.addr:02x} ", style=_STYLE[dk])
    if row._text or row._spans:
        rows.append(row)
    body = Text("\n").join(rows) if rows else Text("no accesses yet", style="dim")
    return Panel(body, title="[head]access grid[/]  [dim](hex addr, colour = result)[/]",
                 border_style="border", padding=(0, 1))


def make_stats(stats: SimStats) -> Panel:
    tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    tbl.add_column("metric", style="label",  min_width=16)
    tbl.add_column("n",      style="bold",   justify="right", min_width=5)
    tbl.add_column("bar",    min_width=34)

    tbl.add_row("L1 hits",  str(stats.l1_hits), _bar(stats.l1_rate,  "l1"))
    tbl.add_row("L2 hits",  str(stats.l2_hits), _bar(stats.l2_rate,  "l2"))
    tbl.add_row("misses",   str(stats.misses),  _bar(stats.miss_rate,"miss"))
    tbl.add_row("", "", Text(""))
    tbl.add_row(
        Text("total accesses", style="label"),
        Text(str(stats.total), style="bold bright_white"), Text(""),
    )
    tbl.add_row(
        Text("avg cycles/access", style="label"),
        Text(f"{stats.avg_cycles:.1f}", style="bold bright_white"), Text(""),
    )
    penalty_style = "miss" if stats.cycle_penalty > 0 else "l1"
    tbl.add_row(
        Text("cycle penalty vs ideal", style="label"),
        Text(f"+{stats.cycle_penalty}", style=penalty_style), Text(""),
    )
    tbl.add_row(
        Text("total cycles", style="label"),
        Text(str(stats.total_cycles), style="bold bright_white"), Text(""),
    )
    return Panel(tbl, title="[head]hit rates & cycle cost[/]", border_style="border", padding=(0, 1))


def make_cache_panel(cache: LRUCache, tick: int) -> Panel:
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1), expand=True)
    tbl.add_column("#",        style="dim",    justify="right", min_width=3)
    tbl.add_column("addr",     style="addr",   min_width=6)
    tbl.add_column("recency",  min_width=16)
    tbl.add_column("age",      style="dim",    min_width=5)

    contents = cache.contents_mru_first()
    if not contents:
        tbl.add_row("—", "empty", Text(""), "—")
    for rank, (addr, last_tick) in enumerate(contents):
        age      = tick - last_tick
        recency  = max(0.0, 1 - age / max(tick, 1))
        bar_len  = round(recency * 14)
        bar      = Text()
        bar.append("█" * bar_len,        style="l1" if rank == 0 else "l2")
        bar.append("░" * (14 - bar_len), style="dim")
        tbl.add_row(
            Text(str(rank + 1), style="l1" if rank == 0 else "dim"),
            f"0x{addr:02x}",
            bar,
            f"t-{age}",
        )
    title = f"[head]{cache.name}[/]  [dim]{len(cache)}/{cache.size} lines[/]"
    return Panel(tbl, title=title, border_style="border", padding=(0, 1))


def make_log(results: list[AccessResult], last_n: int = 14) -> Panel:
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1), expand=True)
    tbl.add_column("#",          style="dim",  justify="right", min_width=4)
    tbl.add_column("addr",       style="addr", min_width=6)
    tbl.add_column("result",     min_width=8)
    tbl.add_column("cy",         justify="right", style="dim", min_width=4)
    tbl.add_column("evictions",  style="evict", min_width=18)

    for i, r in enumerate(reversed(results[-last_n:])):
        idx    = len(results) - i
        evnote = ""
        if r.l1_evict is not None: evnote += f"L1←0x{r.l1_evict:02x} "
        if r.l2_evict is not None: evnote += f"L2←0x{r.l2_evict:02x}"
        tbl.add_row(
            str(idx),
            f"0x{r.addr:02x}",
            Text(r.kind_label.strip(), style=_STYLE[r.kind]),
            str(r.cycles),
            evnote.strip(),
        )
    return Panel(tbl, title="[head]access log[/]", border_style="border", padding=(0, 1))


def make_numpy_summary(results: list[AccessResult]) -> Panel:
    kinds  = np.array([r.kind   for r in results])
    cycles = np.array([r.cycles for r in results])
    addrs  = np.array([r.addr   for r in results])
    ukinds, counts = np.unique(kinds, return_counts=True)

    lines = [
        ("access vector shape",  str(kinds.shape)),
        ("address range",        f"0x{addrs.min():02x} – 0x{addrs.max():02x}"),
        ("unique addresses",     str(len(np.unique(addrs)))),
        ("cycle stats",          f"min={cycles.min()}  max={cycles.max()}  mean={cycles.mean():.1f}  σ={cycles.std():.1f}"),
        ("kind breakdown",       str({k: int(c) for k, c in zip(ukinds, counts)})),
    ]
    tbl = Table(box=None, show_header=False, padding=(0, 2))
    tbl.add_column("key",   style="label",  min_width=22)
    tbl.add_column("value", style="addr")
    for k, v in lines:
        tbl.add_row(k, v)
    return Panel(
        tbl,
        title="[head]numpy summary[/]  [dim]v2.0 bridge: compare against real MCU DWT trace[/]",
        border_style="border",
        padding=(0, 1),
    )


# ─────────────────────────────────────────────────────────────────
#  Animated run
# ─────────────────────────────────────────────────────────────────

def run_animated(
    addresses: list[int],
    l1_size: int   = 4,
    l2_size: int   = 8,
    delay_ms: float = 150.0,
) -> "CacheSimulator":

    sim = CacheSimulator(l1_size=l1_size, l2_size=l2_size)
    console.print()
    console.print(make_header())
    console.print(make_legend())
    console.print()

    with Live(console=console, refresh_per_second=20) as live:
        for addr in addresses:
            r   = sim.access(addr)
            dk  = r.display_kind

            line = Text()
            line.append(f"  {_SYMBOL[dk]} ", style=_STYLE[dk])
            line.append(f"0x{addr:02x}", style="addr")
            line.append("  →  ")
            line.append(f"{r.kind_label}", style=_STYLE[r.kind])
            line.append(f"  {r.cycles:>3} cy   ", style="dim")
            line.append(f"L1: {sim.stats.l1_rate*100:5.1f}%", style="l1")
            line.append("  ")
            line.append(f"L2: {sim.stats.l2_rate*100:5.1f}%", style="l2")
            line.append("  ")
            line.append(f"miss: {sim.stats.miss_rate*100:5.1f}%", style="miss")
            if r.l1_evict is not None:
                line.append(f"   evict 0x{r.l1_evict:02x}→L1", style="evict")
            if r.l2_evict is not None:
                line.append(f"  evict 0x{r.l2_evict:02x}→L2", style="evict")

            live.console.print(line)
            live.update(
                Columns([
                    make_cache_panel(sim.l1, sim._tick),
                    make_cache_panel(sim.l2, sim._tick),
                ])
            )
            time.sleep(delay_ms / 1000.0)

    return sim


def print_final_report(sim: CacheSimulator) -> None:
    console.print()
    console.print(Rule("[head]final report[/]", style="border"))
    console.print()
    console.print(make_grid(sim.results))
    console.print()
    console.print(make_stats(sim.stats))
    console.print()
    console.print(Columns([
        make_cache_panel(sim.l1, sim._tick),
        make_cache_panel(sim.l2, sim._tick),
    ]))
    console.print()
    console.print(make_log(sim.results))
    console.print()
    console.print(make_numpy_summary(sim.results))
    console.print()


# ─────────────────────────────────────────────────────────────────
#  Interactive menu
# ─────────────────────────────────────────────────────────────────

def interactive_menu() -> None:
    console.print()
    console.print(make_header())
    console.print()

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    tbl.add_column("preset",      style="l2",    min_width=14)
    tbl.add_column("description", style="label", min_width=42)
    tbl.add_column("preview",     style="dim")
    for name, seq in PRESETS.items():
        preview = " ".join(str(x) for x in seq[:12]) + (" …" if len(seq) > 12 else "")
        tbl.add_row(name, PRESET_DESC[name], preview)
    console.print(Panel(tbl, title="[head]presets[/]", border_style="border"))
    console.print()

    preset_name = Prompt.ask(
        "[label]preset[/]",
        default="mixed",
        choices=list(PRESETS.keys()) + ["custom"],
        show_choices=False,
    )

    if preset_name == "custom":
        raw       = Prompt.ask("[label]address sequence (space-separated)[/]")
        addresses = [int(x) for x in raw.split() if x.strip().isdigit()]
    else:
        addresses = PRESETS[preset_name]

    l1_size  = int(Prompt.ask("[label]L1 size (lines)[/]",    default="4"))
    l2_size  = int(Prompt.ask("[label]L2 size (lines)[/]",    default="8"))
    delay_ms = float(Prompt.ask("[label]animation delay ms[/]", default="150"))

    console.print()
    sim = run_animated(addresses, l1_size=l1_size, l2_size=l2_size, delay_ms=delay_ms)
    print_final_report(sim)


# ─────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CPU cache hierarchy simulator — L1 + L2 + LRU eviction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python cache_sim.py                           interactive menu
              python cache_sim.py --preset thrash           cache-thrash pattern
              python cache_sim.py --seq "0 1 2 3 0 1 4"    custom sequence
              python cache_sim.py --l1 8 --l2 16 --preset sequential
              python cache_sim.py --no-animate --preset mixed
        """),
    )
    parser.add_argument("--l1",           type=int,   default=4)
    parser.add_argument("--l2",           type=int,   default=8)
    parser.add_argument("--preset",       type=str,   choices=list(PRESETS.keys()))
    parser.add_argument("--seq",          type=str,   default=None)
    parser.add_argument("--delay",        type=float, default=150.0)
    parser.add_argument("--no-animate",   action="store_true")
    parser.add_argument("--list-presets", action="store_true")
    args = parser.parse_args()

    if args.list_presets:
        console.print()
        for name, seq in PRESETS.items():
            console.print(f"  [l2]{name:<16}[/] [label]{PRESET_DESC[name]}[/]")
        console.print()
        return

    if args.preset is None and args.seq is None:
        interactive_menu()
        return

    addresses = (
        [int(x) for x in args.seq.split() if x.strip().isdigit()]
        if args.seq else PRESETS[args.preset]
    )

    if len(addresses) < 10:
        console.print("[miss]warning:[/] fewer than 10 accesses — add more for meaningful stats.")

    if args.no_animate:
        sim = CacheSimulator(l1_size=args.l1, l2_size=args.l2)
        for addr in addresses:
            sim.access(addr)
        console.print(make_header())
    else:
        sim = run_animated(addresses, l1_size=args.l1, l2_size=args.l2, delay_ms=args.delay)

    print_final_report(sim)


if __name__ == "__main__":
    main()