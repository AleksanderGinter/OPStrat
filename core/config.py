"""Pre-race configuration.

Everything in here is set once in the options window (from free-practice data)
and then held as the working assumption for the whole race.  Values the driver
refines live -- measured fuel/lap, measured laptimes -- live in ``state.py``
instead, because they change while the race runs.

The config is a plain dataclass so it can be round-tripped to JSON and diffed
in tests without any Qt involvement.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


class ConfigError(ValueError):
    """Raised when a configuration value would make the maths undefined."""


@dataclass
class RaceConfig:
    """Static, pre-race assumptions.

    Times are seconds, volumes are litres.  Nothing here is mutated by the
    engine at runtime; the options dialog replaces the whole object.
    """

    # --- race ------------------------------------------------------------
    race_length_s: int = 2 * 3600          # 2h00m00s
    track_clockwise: bool = True           # direction the dots travel on the map

    # --- fuel ------------------------------------------------------------
    tank_size_l: float = 100.0
    fuel_per_lap_l: float = 3.10           # free-practice assumption; refined live
    reserve_l: float = 2.0                 # never to be consumed

    # --- "+1 lap" fuel-save target ---------------------------------------
    plus_one_reserve_use: float = 0.70     # fraction of the reserve we may dip into
    plus_one_min_ratio: float = 0.85       # below this * avg fuel/lap, treat as impossible

    # --- pit stop --------------------------------------------------------
    full_tank_fill_s: float = 40.0         # empty -> full; fill scales linearly
    tyre_change_s: float = 20.0            # flat, concurrent with refuelling
    pit_delta_s: float = 45.0              # drive-through loss vs a green-flag lap

    # --- reference laptimes ----------------------------------------------
    gtd_laptime_s: float = 100.0
    gtp_laptime_s: float = 94.0
    gtp_pitstop_s: float = 55.0            # total time GTP loses per stop
    gtp_stops_remaining: int = 1           # expected, decremented by "GTP pitted"

    # --- display ---------------------------------------------------------
    refresh_window_s: int = 5              # 5 or 10; latch period for strategy readouts

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #

    @property
    def fill_rate_l_per_s(self) -> float:
        """Litres delivered per second of refuelling."""
        return self.tank_size_l / self.full_tank_fill_s

    @property
    def usable_tank_l(self) -> float:
        """Tank capacity that may actually be burned."""
        return self.tank_size_l - self.reserve_l

    def validate(self) -> None:
        """Raise :class:`ConfigError` on anything that would break the model.

        Called by the options dialog before the config is accepted, so bad
        input never reaches the engine and turns into a NaN on the driver's
        screen mid-stint.
        """
        if self.race_length_s <= 0:
            raise ConfigError("Race length must be greater than zero.")
        if self.tank_size_l <= 0:
            raise ConfigError("Tank size must be greater than zero.")
        if self.fuel_per_lap_l <= 0:
            raise ConfigError("Fuel per lap must be greater than zero.")
        if self.reserve_l < 0:
            raise ConfigError("Reserve cannot be negative.")
        if self.reserve_l >= self.tank_size_l:
            raise ConfigError("Reserve must be smaller than the tank.")
        if self.usable_tank_l < self.fuel_per_lap_l:
            raise ConfigError(
                "Tank minus reserve is less than one lap of fuel -- no stint is possible."
            )
        if self.full_tank_fill_s <= 0:
            raise ConfigError("Time to fill a full tank must be greater than zero.")
        if self.tyre_change_s < 0 or self.pit_delta_s < 0:
            raise ConfigError("Tyre change and pit delta cannot be negative.")
        if self.gtd_laptime_s <= 0 or self.gtp_laptime_s <= 0:
            raise ConfigError("Laptimes must be greater than zero.")
        if self.gtp_pitstop_s < 0:
            raise ConfigError("GTP pit stop length cannot be negative.")
        if self.gtp_stops_remaining < 0:
            raise ConfigError("GTP stops remaining cannot be negative.")
        if not 0.0 <= self.plus_one_reserve_use <= 1.0:
            raise ConfigError("Reserve usage for +1 lap must be between 0 and 1.")
        if not 0.0 < self.plus_one_min_ratio <= 1.0:
            raise ConfigError("Minimum consumption ratio must be between 0 and 1.")
        if self.refresh_window_s not in (5, 10):
            raise ConfigError("Refresh window must be 5 or 10 seconds.")

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "RaceConfig":
        """Build a config from a dict, ignoring unknown keys.

        Unknown keys are dropped rather than raising so a settings file saved
        by an older build still loads.
        """
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "RaceConfig":
        """Load a config, falling back to defaults if the file is missing or corrupt."""
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError, ValueError):
            return cls()


DEFAULT_CONFIG_PATH = Path.home() / ".imsa_strategy.json"
