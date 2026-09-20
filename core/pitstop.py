"""Pit stop timing.

Refuelling and tyres happen concurrently; repairs are serial and start once the
longer of the two has finished.  The drive-through delta is the time lost
driving the pit lane compared with a green-flag lap, and is added on top.

    total = pit_delta + max(fuel_time, tyre_time) + repair_time
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PitStopBreakdown:
    """A costed pit stop."""

    fuel_l: float
    fuel_time_s: float
    tyres: bool
    tyre_time_s: float
    repair_time_s: float
    delta_s: float

    @property
    def service_time_s(self) -> float:
        """Stationary time: concurrent fuel/tyres, then repairs."""
        return max(self.fuel_time_s, self.tyre_time_s) + self.repair_time_s

    @property
    def total_time_s(self) -> float:
        """Total time lost versus staying on track."""
        return self.delta_s + self.service_time_s

    @property
    def free_fuel_window_s(self) -> float:
        """Seconds of refuelling still 'free' inside the tyre change.

        Positive means fuel finishes before the tyres are on, so more fuel
        could be taken at no cost in time.
        """
        if not self.tyres:
            return 0.0
        return max(0.0, self.tyre_time_s - self.fuel_time_s)

    @property
    def warn_fuel_shorter_than_tyres(self) -> bool:
        """True when the stop is tyre-limited -- free fuel is being left behind."""
        return self.tyres and self.fuel_time_s < self.tyre_time_s - 1e-9


def fill_time_s(litres: float, cfg) -> float:
    """Refuelling time for ``litres``, scaling linearly from the full-tank figure."""
    if litres <= 0:
        return 0.0
    return litres * cfg.full_tank_fill_s / cfg.tank_size_l


def fuel_in_time_s(seconds: float, cfg) -> float:
    """Inverse of :func:`fill_time_s` -- litres deliverable in ``seconds``."""
    if seconds <= 0:
        return 0.0
    return seconds * cfg.tank_size_l / cfg.full_tank_fill_s


def tyre_equivalent_fuel_l(cfg) -> float:
    """Litres whose fill time exactly matches a tyre change.

    Take at least this much at a stop where tyres are changed and the fuel
    costs nothing extra.
    """
    return fuel_in_time_s(cfg.tyre_change_s, cfg)


def build_stop(
    cfg,
    fuel_l: float,
    tyres: bool = True,
    repair_s: float = 0.0,
) -> PitStopBreakdown:
    """Cost a stop from its inputs."""
    return PitStopBreakdown(
        fuel_l=max(0.0, fuel_l),
        fuel_time_s=fill_time_s(fuel_l, cfg),
        tyres=tyres,
        tyre_time_s=cfg.tyre_change_s if tyres else 0.0,
        repair_time_s=max(0.0, repair_s),
        delta_s=cfg.pit_delta_s,
    )
