"""Headless race replay -- the main debugging tool.

Runs the engine with no Qt at all, so you can watch a whole race unfold in a
couple of seconds and see exactly where a number goes wrong.  Two modes:

    # run a clean race to the flag, printing a line per lap
    python -m imsa_strategy.tools.replay

    # replay a scripted scenario and diff the outcome
    python -m imsa_strategy.tools.replay --scenario scenarios/two_stop.json

A scenario is a JSON list of timestamped events::

    {
      "config": {"race_length_s": 7200, "fuel_per_lap_l": 3.1},
      "events": [
        {"t": 0,    "do": "start"},
        {"t": 1800, "do": "fuel_sync", "litres": 42.5},
        {"t": 2400, "do": "pit", "fuel": 50, "tyres": true, "repair": 0},
        {"t": 3000, "do": "gtp_pitted"}
      ]
    }

Because the engine is deterministic, the same scenario always produces the same
table -- which makes it a regression test as well as a debugging aid.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from imsa_strategy.core.config import RaceConfig
from imsa_strategy.core.engine import Engine
from imsa_strategy.core.prediction import format_hms

STEP_S = 1.0


def apply_event(engine: Engine, event: dict) -> str:
    """Apply one scripted event and return a description for the log."""
    action = event.get("do")
    if action == "start":
        engine.start()
        return "clock started"
    if action == "pause":
        engine.pause()
        return "clock paused"
    if action == "fuel_sync":
        engine.fuel_sync(float(event["litres"]))
        return f"fuel sync {event['litres']} L"
    if action == "pit":
        stop = engine.commit_pit(
            float(event.get("fuel", 0.0)),
            bool(event.get("tyres", True)),
            float(event.get("repair", 0.0)),
        )
        return f"PIT {stop.fuel_l:.1f} L, {stop.total_time_s:.1f}s lost"
    if action == "gtp_pitted":
        engine.gtp_pitted()
        return "GTP pitted"
    if action == "gtd_sync":
        engine.gtd_sync()
        return "GTD sync"
    if action == "gtp_sync":
        engine.gtp_sync()
        return "GTP sync"
    return f"unknown event {action!r}"


def run(config: RaceConfig, events: list[dict], verbose: bool = True) -> Engine:
    """Run a race to the flag, applying events at their timestamps."""
    engine = Engine(config)
    engine.start()
    pending = sorted(events, key=lambda e: e.get("t", 0))
    last_lap = engine.state.gtd_lap

    if verbose:
        print(f"{'clock':>9} {'lap':>4} {'left':>5} {'topit':>6} "
              f"{'fuel':>7} {'L/lap':>6} {'stops':>6}  note")

    guard = 0
    while engine.state.elapsed_s < config.race_length_s + 600 and guard < 200_000:
        guard += 1
        engine.tick(STEP_S)

        note = ""
        while pending and pending[0].get("t", 0) <= engine.state.elapsed_s:
            note = apply_event(engine, pending.pop(0))

        if engine.state.gtd_lap != last_lap or note:
            last_lap = engine.state.gtd_lap
            d = engine.derived()
            if verbose:
                print(
                    f"{format_hms(engine.state.elapsed_s):>9} "
                    f"{d.gtd_lap:>4} {d.gtd_laps_left:>5} {d.laps_to_pit:>6} "
                    f"{d.fuel_left_l:>7.1f} {d.fuel_per_lap_l:>6.2f} "
                    f"{d.plan.stop_count if d.plan else 0:>6}  {note}"
                )

        # Invariants: shout early rather than showing a wrong number quietly.
        assert engine.state.fuel_at_lap_start_l >= -1e-6, "negative fuel"
        assert engine.state.gtd_lap >= 1, "lap counter fell below 1"

        if engine.derived().gtd_laps_left <= 1 and engine.state.elapsed_s > config.race_length_s:
            break

    if verbose:
        d = engine.derived()
        print(f"\nflag at {format_hms(engine.state.elapsed_s)}  "
              f"GTD lap {d.gtd_lap}  stops made {engine.state.stops_done}")
    return engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, help="JSON scenario file")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    config = RaceConfig()
    events: list[dict] = []

    if args.scenario:
        data = json.loads(args.scenario.read_text(encoding="utf-8"))
        config = RaceConfig.from_dict({**asdict(config), **data.get("config", {})})
        events = data.get("events", [])

    config.validate()
    run(config, events, verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
