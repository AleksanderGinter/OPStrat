# IMSA strategy board — GTD

A standalone endurance-racing strategy board. Tracks laps remaining for a GTD
car under the IMSA finishing rule: the race ends when the **GTP leader** crosses
the line after the clock expires, and everyone else finishes on their own next
crossing.

Entirely manual — no telemetry, no API, no sim integration. Values come from
free practice, are set in the options window, and are refined live by the
driver or engineer as better data arrives.

## Running it

```bash
pip install -r requirements.txt
python -m imsa_strategy.main
```

In PyCharm: mark the parent folder as sources root, or just run `main.py`
directly — it fixes up `sys.path` itself.

## Layout

```
imsa_strategy/
├── core/               # headless model — imports no Qt
│   ├── config.py       # pre-race settings, JSON persistence, validation
│   ├── state.py        # mutable race state (the single source of truth)
│   ├── fuel.py         # laps to pit, +1 lap target, consumption averaging
│   ├── pitstop.py      # stop timing
│   ├── prediction.py   # flag time, laps left, catch delta
│   ├── strategy.py     # multi-stop fuel plan solver
│   └── engine.py       # applies events, produces the Derived snapshot
├── ui/                 # Qt views — render Derived, never compute
├── tools/replay.py     # headless race replay (the main debugging tool)
├── tests/              # pytest suite over the core
└── scenarios/          # scripted races for replay
```

## How the loops are prevented

Data flow is strictly one-directional:

```
widget  ──command──▶  Engine  ──Derived snapshot──▶  widget
```

* Views hold no state and compute nothing. They render a `Derived` object
  produced by pure functions, so rendering can never mutate the race.
* Widgets never talk to each other — only to the engine.
* Programmatic writes to spin boxes are wrapped in `blockSignals`, which is
  what stops the classic `setValue → valueChanged → model → setValue` cycle.
* Every loop in the model is bounded: lap durations are clamped above 0.1 s,
  the lap-advance loop is capped, and the strategy solver's fixed-point
  iteration runs at most six passes and reports non-convergence rather than
  spinning.

## Timing

* **Model tick: 100 ms.** Race clock, fuel gauge and the dots on the map.
* **Refresh window: 5 s (or 10 s).** Strategy readouts — laps left, laps to
  pit, fuel/lap, the plan. Latching these stops them flickering between two
  values on a boundary.
* **Never latched:** the pit-warning flash, and anything just typed or clicked.
  Driver actions apply immediately.

## Decisions worth knowing

**Laps left is not `time_left / laptime`.** It's a two-stage calculation — when
the GTP leader takes the flag, then our first crossing at or after that moment.
In the default two-hour setup the naive formula gives 72 laps; the correct
answer is 73.

**Laps-to-pit convention.** `0` = pit at the end of the current lap (red);
`1` = pit at the end of the next lap (yellow). Mute silences the blink but
keeps the colour, because a silent green readout during a fuel emergency is
worse than an annoying one.

**Fuel/lap is measured, not assumed, once you sync.** With no telemetry the
only real measurement is between two Fuel Sync entries. Out-laps are excluded
from the average, and inconsistent entries (more fuel than before, with no
stop) are rejected rather than allowed to poison the figure.

**The penultimate stop is not simply minimised.** The original rule was to take
the least possible fuel at the second-to-last stop. That turns out to lose
time: a fill shorter than the tyre change throws away time that is being spent
anyway. So the penultimate stop takes the smallest fill that *still fills the
tyre window*. In the default setup this is worth about 7 seconds — see
`test_the_tyre_window_split_is_not_slower_than_minimising_the_penultimate`.

**GTP stops are carried as padding.** Every stop GTP is still expected to make
delays the predicted flag from the start. Pressing "GTP pitted" converts an
expected stop into a real one, so laps-left stays put instead of lurching by a
whole lap the moment the leader stops.

## Debugging

**1. Replay a race headlessly.** No GUI, deterministic, a line per lap:

```bash
python -m imsa_strategy.tools.replay
python -m imsa_strategy.tools.replay --scenario scenarios/two_stop.json
```

Scenarios are JSON event lists with timestamps, so any bug you hit on the pit
wall can be reproduced exactly and kept as a regression test.

**2. Time warp.** The toolbar button cycles ×1 / ×10 / ×60, so a two-hour race
runs in two minutes and a whole stint can be watched in seconds. This is the
fastest way to check the flash timings and the strategy boxes rebuilding.

**3. Unit tests.**

```bash
pytest imsa_strategy/tests -q
```

The boundaries that matter — laps-to-pit off-by-ones, the flag calculation, the
tyre-window split, solver termination — are pinned explicitly.

**4. Invariants.** `replay.py` asserts on negative fuel and a lap counter below
1 on every step. If a display value looks wrong, run the same inputs through
replay: an assertion usually fires several laps before the symptom shows.

**5. Suggested first checks on a real race.** Before trusting it live, verify:
laps left at the green flag against a hand calculation; the flash turning amber
exactly one lap before the tank rule says to pit; the plan rebuilding from two
boxes to one after the first stop; and laps-left *not* moving when you press
"GTP pitted".

## Known limits

* No full-course-yellow handling. The clock can be paused, but laptimes and
  consumption under caution are not modelled.
* The pit stop is modelled as happening at the line. Real pit entry/exit
  offsets are not accounted for, so on tracks with a long pit lane the lap the
  stop lands on may be out by a fraction.
* GTP is modelled from a single reference laptime. Its stops are assumed to
  fall before the flag.
