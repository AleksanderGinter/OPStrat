"""Fuel maths.

Pure functions only -- no state, no Qt.  Everything here is directly unit
testable, which matters because an off-by-one in ``laps_to_pit`` is the kind of
bug that empties a tank at 190 mph.

Convention for ``laps_to_pit`` (agreed with the driver):

    laps_to_pit == 0  ->  pit at the end of the CURRENT lap   (red)
    laps_to_pit == 1  ->  pit at the end of the NEXT lap      (yellow)
    laps_to_pit >= 2  ->  no warning

It counts complete laps that can still be started *after* the one in progress,
with the reserve left untouched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class PitUrgency(Enum):
    """Flash state for the laps-to-pit readout."""

    NONE = "none"
    NEXT_LAP = "next_lap"   # yellow
    THIS_LAP = "this_lap"   # red
    OVERDUE = "overdue"     # red, and the reserve is already being eaten


def laps_possible(fuel_l: float, fuel_per_lap_l: float, reserve_l: float) -> int:
    """Whole laps that can be completed from ``fuel_l`` without touching the reserve."""
    if fuel_per_lap_l <= 0:
        return 0
    usable = fuel_l - reserve_l
    if usable < fuel_per_lap_l:
        return 0
    return int(math.floor(usable / fuel_per_lap_l + 1e-9))


def laps_to_pit(
    fuel_at_lap_start_l: float, fuel_per_lap_l: float, reserve_l: float
) -> int:
    """Laps still available *after* the lap in progress.

    The driver is mid-lap, so the current lap's fuel is already committed; what
    matters is what will be in the tank at the next line crossing.  Returns -1
    when the current lap itself cannot be completed on the usable fuel, which
    the UI shows as OVERDUE.
    """
    fuel_at_next_line = fuel_at_lap_start_l - fuel_per_lap_l
    if fuel_at_next_line < reserve_l - 1e-9:
        # The current lap will already dip into the reserve.
        return -1 if fuel_at_lap_start_l < reserve_l else 0
    return laps_possible(fuel_at_next_line, fuel_per_lap_l, reserve_l)


def pit_urgency(laps_left_to_pit: int) -> PitUrgency:
    if laps_left_to_pit < 0:
        return PitUrgency.OVERDUE
    if laps_left_to_pit == 0:
        return PitUrgency.THIS_LAP
    if laps_left_to_pit == 1:
        return PitUrgency.NEXT_LAP
    return PitUrgency.NONE


def time_to_pit_s(
    laps_left_to_pit: int, lap_remaining_s: float, laptime_s: float
) -> float:
    """Seconds until the driver must be in the pit lane."""
    return max(0.0, lap_remaining_s + max(0, laps_left_to_pit) * laptime_s)


@dataclass
class PlusOneTarget:
    """The 'save fuel to gain a lap' readout."""

    target_l_per_lap: float
    achievable: bool
    extended_stint_laps: int

    @property
    def display(self) -> str:
        return f"{self.target_l_per_lap:.2f}"


def plus_one_lap_target(
    fuel_at_lap_start_l: float,
    fuel_per_lap_l: float,
    reserve_l: float,
    reserve_use: float,
    min_ratio: float,
) -> PlusOneTarget | None:
    """Maximum consumption that would stretch the stint by one more lap.

    The stint currently runs to the end of the current lap plus
    ``laps_to_pit`` more.  To add one lap on top of that we are allowed to eat
    ``reserve_use`` of the reserve (default 70%), leaving the rest as a hard
    floor.

    Marked unachievable -- and greyed out by the UI -- when the required figure
    falls below ``min_ratio`` (default 85%) of the current average, because no
    amount of lifting and coasting gets a car there.
    """
    remaining = laps_to_pit(fuel_at_lap_start_l, fuel_per_lap_l, reserve_l)
    if remaining < 0:
        return None
    stint_laps = 1 + remaining          # current lap plus whatever follows
    extended = stint_laps + 1
    available = fuel_at_lap_start_l - reserve_l * (1.0 - reserve_use)
    if available <= 0 or extended <= 0:
        return None
    target = available / extended
    return PlusOneTarget(
        target_l_per_lap=target,
        achievable=target >= min_ratio * fuel_per_lap_l,
        extended_stint_laps=extended,
    )


def measure_fuel_per_lap(
    fuel_at_window_start_l: float,
    fuel_now_l: float,
    fuel_added_l: float,
    laps_in_window: int,
    out_laps: int = 0,
) -> float | None:
    """Average consumption between two Fuel Sync entries.

    ``out_laps`` (the first lap of any stint) are excluded from the denominator
    because they are not representative -- as is race lap 1, which the engine
    handles by not opening a measurement window until lap 2.

    Returns ``None`` when the window is too short or the numbers are
    inconsistent (e.g. the driver typed more fuel than could be aboard), so a
    fat-fingered entry never poisons the average.
    """
    usable_laps = laps_in_window - out_laps
    if usable_laps < 1:
        return None
    consumed = fuel_at_window_start_l + fuel_added_l - fuel_now_l
    if consumed <= 0:
        return None
    result = consumed / usable_laps
    if result <= 0 or result > 100:   # sanity bound; no GT car burns 100 L/lap
        return None
    return result


def stint_laps_on_full_tank(
    tank_l: float, fuel_per_lap_l: float, reserve_l: float
) -> int:
    """Longest stint a full tank supports."""
    return laps_possible(tank_l, fuel_per_lap_l, reserve_l)


def fuel_for_laps(laps: int, fuel_per_lap_l: float, reserve_l: float) -> float:
    """Fuel needed to run ``laps`` laps and still have the reserve aboard."""
    return max(0.0, laps * fuel_per_lap_l + reserve_l)
