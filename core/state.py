"""Live race state -- the single source of truth.

Design note (this is what keeps the app out of feedback loops):

* Nothing in this module computes a *derived* display value.  It stores only
  facts: where the cars are, how much fuel is aboard, what the driver typed.
* Car position is stored as an **anchor**, not as an integrated phase.  We keep
  the race-clock time at which the current lap started and the duration of that
  lap; phase is recomputed from the clock every tick.  That means the dots can
  never drift out of sync with the clock, and a paused clock freezes them
  exactly.
* Every derived number (laps left, laps to pit, delta, the strategy plan) is a
  pure function of ``RaceConfig`` + ``RaceState``, computed on demand in the
  other core modules.  Views never write to each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How many previous GTD laps the right-hand column shows.
LAPTIME_HISTORY = 10


@dataclass
class LapSample:
    """One measured GTD lap.

    ``pinned`` marks a row the driver nudged with the +/- 0.2 s buttons, so an
    incoming measurement does not silently overwrite a deliberate override.
    """

    seconds: float
    pinned: bool = False


@dataclass
class RaceState:
    """Everything that changes while the race runs."""

    # --- clock -----------------------------------------------------------
    elapsed_s: float = 0.0
    running: bool = False

    # --- GTD car (ours) --------------------------------------------------
    gtd_lap: int = 1                # lap currently being run
    gtd_lap_start_s: float = 0.0    # race-clock time this lap began
    gtd_lap_extra_s: float = 0.0    # pit time added to the *current* lap only

    # --- GTP leader ------------------------------------------------------
    gtp_lap: int = 1
    gtp_lap_start_s: float = 0.0
    gtp_lap_extra_s: float = 0.0
    gtp_stops_remaining: int = 1    # seeded from config, decremented on "GTP pitted"

    # --- fuel ------------------------------------------------------------
    fuel_at_lap_start_l: float = 0.0   # fuel aboard as the current lap began

    # Consumption measurement window.  Fuel/lap can only be *measured* between
    # two Fuel Sync entries, because the app has no telemetry.
    sync_fuel_l: float | None = None    # fuel reading at the window's start
    sync_lap: int = 1                   # lap number at the window's start
    sync_fuel_added_l: float = 0.0      # fuel added during the window
    sync_out_laps: int = 0              # out-laps inside the window (excluded)
    measured_fuel_per_lap_l: float | None = None

    # --- laptimes --------------------------------------------------------
    laptimes: list[LapSample] = field(default_factory=list)

    # --- pit -------------------------------------------------------------
    stops_done: int = 0
    last_stop_lap: int | None = None

    # --- ui ---------------------------------------------------------------
    muted: bool = False
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #

    def seed(self, cfg) -> None:
        """Initialise state from a config, as at the moment the app opens."""
        self.fuel_at_lap_start_l = cfg.tank_size_l
        self.gtp_stops_remaining = cfg.gtp_stops_remaining
        self.laptimes = [LapSample(cfg.gtd_laptime_s) for _ in range(LAPTIME_HISTORY)]
        self.sync_fuel_l = None
        self.sync_lap = 1

    # --- laptime helpers ------------------------------------------------

    def reference_laptime_s(self, cfg) -> float:
        """Working GTD laptime: the mean of the history rows.

        The rows are seeded from the configured free-practice laptime, so
        before any real lap is recorded this simply returns that value.
        """
        if not self.laptimes:
            return cfg.gtd_laptime_s
        return sum(s.seconds for s in self.laptimes) / len(self.laptimes)

    def push_laptime(self, seconds: float) -> None:
        """Record a measured lap at the head of the history.

        Pinned rows are preserved: the new sample displaces the most recent
        unpinned row instead of shifting a driver override off the end.
        """
        self.laptimes.insert(0, LapSample(seconds))
        while len(self.laptimes) > LAPTIME_HISTORY:
            # Drop the oldest unpinned row; if every row is pinned, drop the oldest.
            for i in range(len(self.laptimes) - 1, -1, -1):
                if not self.laptimes[i].pinned:
                    del self.laptimes[i]
                    break
            else:
                del self.laptimes[-1]

    # --- position helpers -----------------------------------------------

    def gtd_lap_duration_s(self, cfg) -> float:
        """Duration of the lap currently in progress, including any pit time."""
        return max(0.1, self.reference_laptime_s(cfg) + self.gtd_lap_extra_s)

    def gtp_lap_duration_s(self, cfg) -> float:
        return max(0.1, cfg.gtp_laptime_s + self.gtp_lap_extra_s)

    def gtd_phase(self, cfg) -> float:
        """Fraction of the current lap completed, 0.0 at the line."""
        return _phase(self.elapsed_s - self.gtd_lap_start_s, self.gtd_lap_duration_s(cfg))

    def gtp_phase(self, cfg) -> float:
        return _phase(self.elapsed_s - self.gtp_lap_start_s, self.gtp_lap_duration_s(cfg))

    # --- fuel helpers ----------------------------------------------------

    def fuel_now_l(self, cfg, fuel_per_lap_l: float) -> float:
        """Live fuel, interpolated across the current lap.

        The model value steps at the line; this smooths it for display so the
        gauge does not sit still for 100 s and then jump.
        """
        burned = fuel_per_lap_l * self.gtd_phase(cfg)
        return max(0.0, self.fuel_at_lap_start_l - burned)


def _phase(delta_s: float, duration_s: float) -> float:
    if duration_s <= 0:
        return 0.0
    return min(1.0, max(0.0, delta_s / duration_s))
