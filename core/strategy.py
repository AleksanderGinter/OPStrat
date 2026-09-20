"""Fuel strategy solver.

Produces the row of boxes under the track map: how many stops are left, and how
much fuel to take at each.

Three tiers, as agreed:

* **Early stops (1 .. n-2)** -- fill to the largest whole-lap amount the tank
  supports, and no more.  Extra fuel beyond a whole lap is dead weight that
  also costs time going in.
* **Penultimate stop (n-1)** -- the *smallest* fill that still reaches the last
  stop, chosen so the final stop has enough fuel to take that its fill time
  covers the tyre change.
* **Final stop (n)** -- the minimum fuel that reaches the flag, but preferably
  raised to the tyre-equivalent amount, because fuel taken inside the tyre
  window is free.

With two stops (the expected case) tier one is empty and the plan is just
penultimate + final.  With one stop it collapses to the final rule alone.

Circular dependency, and how it is broken
-----------------------------------------
Laps left depends on how much time we lose in the pits; the number of stops
depends on laps left.  ``solve`` runs a **bounded** fixed-point iteration -- at
most ``_MAX_PASSES`` passes, returning the last result and flagging
non-convergence rather than looping forever.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import fuel as fuel_math
from . import pitstop, prediction

_MAX_PASSES = 6


@dataclass
class PlannedStop:
    """One projected stop in the plan."""

    index: int              # 1-based, counting stops still to come
    fuel_l: float
    laps_covered: int       # laps this fill is good for
    fill_time_s: float
    total_time_s: float
    is_final: bool
    note: str = ""


@dataclass
class StrategyPlan:
    """The whole remaining plan."""

    laps_left: int                          # to the chequered flag, including current lap
    laps_on_current_fuel: int               # current lap plus laps_to_pit
    stops: list[PlannedStop] = field(default_factory=list)
    total_pit_time_s: float = 0.0
    converged: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def stop_count(self) -> int:
        return len(self.stops)


def _build_plan(
    cfg,
    laps_left: int,
    laps_on_current_fuel: int,
    fuel_per_lap_l: float,
    tyres_planned: bool = True,
) -> StrategyPlan:
    """Lay out the stops for a known number of laps left.

    Pure: no state, no iteration over the race clock.
    """
    plan = StrategyPlan(laps_left=laps_left, laps_on_current_fuel=laps_on_current_fuel)

    laps_to_cover = laps_left - laps_on_current_fuel
    if laps_to_cover <= 0:
        return plan   # we can make the flag on what is aboard

    stint_max = fuel_math.stint_laps_on_full_tank(
        cfg.tank_size_l, fuel_per_lap_l, cfg.reserve_l
    )
    if stint_max < 1:
        plan.warnings.append("Tank cannot cover a single lap -- check fuel settings.")
        return plan

    n_stops = math.ceil(laps_to_cover / stint_max)
    n_stops = max(1, min(n_stops, 60))   # bound: a plan of 60 stops is a config error

    tyre_equiv_l = pitstop.tyre_equivalent_fuel_l(cfg) if tyres_planned else 0.0

    # --- distribute laps across the stints ----------------------------- #
    if n_stops == 1:
        stint_laps = [laps_to_cover]
    else:
        early = n_stops - 2
        covered_early = early * stint_max
        # Because n_stops is the minimum, this is always > stint_max, so both
        # of the last two stints are guaranteed at least one lap.
        remaining_two = laps_to_cover - covered_early

        # Laps whose fuel takes exactly as long to pour as a tyre change.  A
        # fill shorter than this wastes part of the tyre window: the time is
        # being spent anyway, so the fuel is free up to this point.
        min_window_laps = 0
        if tyre_equiv_l > cfg.reserve_l:
            min_window_laps = math.ceil(
                (tyre_equiv_l - cfg.reserve_l) / fuel_per_lap_l - 1e-9
            )

        # Penultimate stop: as small as possible (least fuel carried, least
        # weight), subject to two constraints --
        #   * the final stint must fit in one tank        -> >= remaining_two - stint_max
        #   * this fill must not waste the tyre window    -> >= min_window_laps
        penultimate_laps = max(1, remaining_two - stint_max, min_window_laps)
        penultimate_laps = min(penultimate_laps, remaining_two - 1, stint_max)
        penultimate_laps = max(1, penultimate_laps)

        final_laps = remaining_two - penultimate_laps

        if final_laps > stint_max:
            plan.warnings.append(
                "Final stint will not fit in one tank -- an extra stop may be needed."
            )
        if min_window_laps > stint_max:
            plan.warnings.append(
                "A full tank fills faster than a tyre change -- every stop is "
                "tyre-limited."
            )

        stint_laps = [stint_max] * early + [penultimate_laps, final_laps]

    # --- turn stint lengths into fills ---------------------------------- #
    for i, laps in enumerate(stint_laps, start=1):
        is_final = i == len(stint_laps)
        needed = fuel_math.fuel_for_laps(laps, fuel_per_lap_l, cfg.reserve_l)
        note = ""

        if is_final:
            if tyres_planned and needed < tyre_equiv_l <= cfg.tank_size_l:
                needed = tyre_equiv_l
                note = "raised to fill the tyre window"
        else:
            # Never carry more than the tank, and never more than the stint needs.
            needed = min(needed, cfg.tank_size_l)

        needed = min(needed, cfg.tank_size_l)
        stop = pitstop.build_stop(cfg, needed, tyres=tyres_planned, repair_s=0.0)
        plan.stops.append(
            PlannedStop(
                index=i,
                fuel_l=needed,
                laps_covered=laps,
                fill_time_s=stop.fuel_time_s,
                total_time_s=stop.total_time_s,
                is_final=is_final,
                note=note,
            )
        )

    plan.total_pit_time_s = sum(s.total_time_s for s in plan.stops)
    return plan


def solve(state, cfg, fuel_per_lap_l: float, tyres_planned: bool = True) -> StrategyPlan:
    """Solve laps-left and the stop plan together.

    Bounded fixed point: start with a plan that assumes no pit time, cost it,
    recompute laps left with that cost, and repeat until the lap count stops
    moving.  Bails after ``_MAX_PASSES`` and flags ``converged = False`` rather
    than spinning.
    """
    laps_on_current_fuel = 1 + max(
        0, fuel_math.laps_to_pit(state.fuel_at_lap_start_l, fuel_per_lap_l, cfg.reserve_l)
    )

    pit_time = 0.0
    plan: StrategyPlan | None = None
    last_laps = -1
    converged = False

    for _ in range(_MAX_PASSES):
        end = prediction.predict_end(state, cfg, our_pit_time_s=pit_time)
        laps_left = end.gtd_laps_left
        plan = _build_plan(
            cfg, laps_left, laps_on_current_fuel, fuel_per_lap_l, tyres_planned
        )
        if laps_left == last_laps:
            converged = True
            break
        last_laps = laps_left
        pit_time = plan.total_pit_time_s

    assert plan is not None
    plan.converged = converged
    if not converged:
        plan.warnings.append(
            "Lap count did not settle -- pit time and laps left are on a knife edge."
        )
    return plan
