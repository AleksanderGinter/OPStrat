"""The engine: the only object the UI talks to.

Data flow is strictly one-directional, which is what prevents the classic
PySide6 feedback loop (``setValue`` -> ``valueChanged`` -> model -> widget):

    widget  --command-->  Engine  --Derived snapshot-->  widget

Widgets never compute anything and never talk to each other.  They call a
command method, then read a fresh :class:`Derived` snapshot.  ``Derived`` is
produced by pure functions and has no side effects, so rendering it can never
mutate the race.

The engine imports no Qt, so the whole race model runs headless under pytest
and in ``tools/replay.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import fuel as fuel_math
from . import pitstop, prediction, strategy
from .config import RaceConfig
from .state import RaceState

# A manual line-crossing is only accepted as a laptime measurement if it falls
# in this band around the reference lap.  Stops a stray double-click from
# recording a 3-second "lap".
_LAPTIME_ACCEPT_MIN = 0.5
_LAPTIME_ACCEPT_MAX = 2.5


@dataclass
class Derived:
    """Everything the UI displays, computed fresh from config + state."""

    # clock / race
    time_left_s: float = 0.0
    time_left_hms: str = "00:00:00"
    running: bool = False
    gtd_laps_left: int = 0

    # pit window
    laps_to_pit: int = 0
    time_to_pit_s: float = 0.0
    time_to_pit_ms: str = "00:00"
    urgency: fuel_math.PitUrgency = fuel_math.PitUrgency.NONE

    # fuel
    fuel_left_l: float = 0.0
    fuel_per_lap_l: float = 0.0
    fuel_per_lap_is_measured: bool = False
    plus_one_target_l: float | None = None
    plus_one_achievable: bool = False

    # track map
    gtd_lap: int = 1
    gtp_lap: int = 1
    gtd_phase: float = 0.0
    gtp_phase: float = 0.0
    catch_delta_s: float | None = None

    # plan
    plan: strategy.StrategyPlan | None = None

    # laptimes
    reference_laptime_s: float = 0.0
    laptimes: list[float] = field(default_factory=list)

    notes: list[str] = field(default_factory=list)


class Engine:
    """Owns the config and the state, and applies every event."""

    def __init__(self, config: RaceConfig | None = None) -> None:
        self.config = config or RaceConfig()
        self.state = RaceState()
        self.state.seed(self.config)
        self._plan_cache: strategy.StrategyPlan | None = None
        self._plan_dirty = True

    # ------------------------------------------------------------------ #
    # Clock
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        self.state.running = True

    def pause(self) -> None:
        self.state.running = False

    def toggle_clock(self) -> None:
        self.state.running = not self.state.running

    def tick(self, dt_s: float) -> None:
        """Advance the race by ``dt_s`` seconds of wall time.

        Called at ~10 Hz by the UI so the clock and the dots move smoothly;
        the strategy readouts are latched to the 5/10 s refresh window by the
        view layer, not here.
        """
        if not self.state.running or dt_s <= 0:
            return
        self.state.elapsed_s += dt_s
        self._advance_laps()

    def _advance_laps(self) -> None:
        """Roll the lap counters forward for any lines crossed since last tick.

        Bounded loop: a lap duration is clamped to >= 0.1 s in ``RaceState``,
        and the iteration count is capped, so a bad laptime cannot hang the
        UI thread.
        """
        cfg, st = self.config, self.state

        for _ in range(1000):
            duration = st.gtd_lap_duration_s(cfg)
            if st.elapsed_s - st.gtd_lap_start_s < duration:
                break
            st.gtd_lap_start_s += duration
            st.gtd_lap += 1
            st.fuel_at_lap_start_l = max(
                0.0, st.fuel_at_lap_start_l - self.fuel_per_lap_l()
            )
            st.gtd_lap_extra_s = 0.0
            self._plan_dirty = True

        for _ in range(1000):
            duration = st.gtp_lap_duration_s(cfg)
            if st.elapsed_s - st.gtp_lap_start_s < duration:
                break
            st.gtp_lap_start_s += duration
            st.gtp_lap += 1
            st.gtp_lap_extra_s = 0.0
            self._plan_dirty = True

    # ------------------------------------------------------------------ #
    # Fuel
    # ------------------------------------------------------------------ #

    def fuel_per_lap_l(self) -> float:
        """Working consumption: measured if we have a measurement, else configured."""
        if self.state.measured_fuel_per_lap_l:
            return self.state.measured_fuel_per_lap_l
        return self.config.fuel_per_lap_l

    def fuel_sync(self, litres: float) -> None:
        """Driver types the actual fuel remaining right now.

        This is the app's only real measurement, so it does two jobs: it
        re-anchors the fuel level, and it closes a consumption window to
        produce a measured fuel/lap.  Out-laps inside the window are excluded.
        """
        cfg, st = self.config, self.state
        litres = max(0.0, min(litres, cfg.tank_size_l))

        if st.sync_fuel_l is not None:
            laps = st.gtd_lap - st.sync_lap
            measured = fuel_math.measure_fuel_per_lap(
                fuel_at_window_start_l=st.sync_fuel_l,
                fuel_now_l=litres,
                fuel_added_l=st.sync_fuel_added_l,
                laps_in_window=laps,
                out_laps=st.sync_out_laps,
            )
            if measured is not None:
                st.measured_fuel_per_lap_l = measured
                st.notes.append(f"Fuel/lap measured at {measured:.2f} L over {laps} lap(s).")

        # Re-anchor: the entry is live fuel, so back out the part of this lap
        # already burned to get the lap-start figure.
        phase = st.gtd_phase(cfg)
        st.fuel_at_lap_start_l = min(
            cfg.tank_size_l, litres + self.fuel_per_lap_l() * phase
        )

        # Open a fresh window.
        st.sync_fuel_l = litres
        st.sync_lap = st.gtd_lap
        st.sync_fuel_added_l = 0.0
        st.sync_out_laps = 0
        self._plan_dirty = True

    # ------------------------------------------------------------------ #
    # Pit stop
    # ------------------------------------------------------------------ #

    def commit_pit(
        self, fuel_l: float, tyres: bool = True, repair_s: float = 0.0
    ) -> pitstop.PitStopBreakdown:
        """Record a stop: add the time to the current lap and the fuel to the tank.

        The stop is modelled as happening at the line, so the lap in progress
        simply takes longer.  The next lap is an out-lap and is excluded from
        the consumption average.
        """
        cfg, st = self.config, self.state
        space = max(0.0, cfg.tank_size_l - st.fuel_at_lap_start_l)
        added = min(max(0.0, fuel_l), space)

        stop = pitstop.build_stop(cfg, added, tyres=tyres, repair_s=repair_s)
        st.gtd_lap_extra_s += stop.total_time_s
        st.fuel_at_lap_start_l = min(cfg.tank_size_l, st.fuel_at_lap_start_l + added)
        st.sync_fuel_added_l += added
        st.sync_out_laps += 1
        st.stops_done += 1
        st.last_stop_lap = st.gtd_lap

        if added < fuel_l - 1e-6:
            st.notes.append(
                f"Fill capped at {added:.1f} L -- the tank would have overflowed."
            )
        self._plan_dirty = True
        return stop

    def preview_pit(
        self, fuel_l: float, tyres: bool = True, repair_s: float = 0.0
    ) -> pitstop.PitStopBreakdown:
        """Cost a stop without committing it (for the live breakdown and warning)."""
        return pitstop.build_stop(self.config, fuel_l, tyres=tyres, repair_s=repair_s)

    # ------------------------------------------------------------------ #
    # Track map / sync
    # ------------------------------------------------------------------ #

    def gtd_sync(self) -> None:
        """Driver presses Sync as they cross the line.

        Snaps our dot to the line, rounds the lap counter to whichever whole
        lap is nearer, and -- if the interval since the last line event looks
        like a plausible lap -- records it as a measured laptime.
        """
        cfg, st = self.config, self.state
        phase = st.gtd_phase(cfg)
        interval = st.elapsed_s - st.gtd_lap_start_s
        reference = st.reference_laptime_s(cfg)

        if _LAPTIME_ACCEPT_MIN <= interval / max(0.1, reference) <= _LAPTIME_ACCEPT_MAX:
            # A real lap: record it, net of any pit time on that lap.
            measured = max(1.0, interval - st.gtd_lap_extra_s)
            st.push_laptime(measured)

        if phase >= 0.5:
            st.gtd_lap += 1          # we were most of the way round: count the lap
            st.fuel_at_lap_start_l = max(
                0.0, st.fuel_at_lap_start_l - self.fuel_per_lap_l()
            )
        st.gtd_lap_start_s = st.elapsed_s
        st.gtd_lap_extra_s = 0.0
        self._plan_dirty = True

    def gtp_sync(self) -> None:
        """Put the GTP dot on top of ours and zero the delta."""
        cfg, st = self.config, self.state
        phase = st.gtd_phase(cfg)
        st.gtp_lap_extra_s = 0.0
        st.gtp_lap_start_s = st.elapsed_s - phase * st.gtp_lap_duration_s(cfg)
        self._plan_dirty = True

    def gtp_pitted(self) -> None:
        """GTP has just made a stop: bank the real time, drop one expected stop.

        Because the prediction already carried this stop as padding, the
        displayed laps left stays put instead of lurching.
        """
        st = self.state
        st.gtp_lap_extra_s += self.config.gtp_pitstop_s
        st.gtp_stops_remaining = max(0, st.gtp_stops_remaining - 1)
        self._plan_dirty = True

    def adjust_gtd_lap(self, delta: int) -> None:
        """Manual +/- on our lap counter.

        Guarded at 1: a zero or negative lap number would divide by zero in the
        consumption window.
        """
        st = self.state
        st.gtd_lap = max(1, st.gtd_lap + delta)
        st.sync_lap = min(st.sync_lap, st.gtd_lap)
        self._plan_dirty = True

    def adjust_gtp_lap(self, delta: int) -> None:
        self.state.gtp_lap = max(1, self.state.gtp_lap + delta)
        self._plan_dirty = True

    def adjust_gtp_stops(self, delta: int) -> None:
        self.state.gtp_stops_remaining = max(0, self.state.gtp_stops_remaining + delta)
        self._plan_dirty = True

    # ------------------------------------------------------------------ #
    # Laptimes
    # ------------------------------------------------------------------ #

    def nudge_laptime(self, index: int, delta_s: float) -> None:
        """+/- 0.2 s on one history row; marks it pinned."""
        if 0 <= index < len(self.state.laptimes):
            row = self.state.laptimes[index]
            row.seconds = max(1.0, row.seconds + delta_s)
            row.pinned = True
            self._plan_dirty = True

    def set_laptime(self, index: int, seconds: float) -> None:
        if 0 <= index < len(self.state.laptimes):
            self.state.laptimes[index].seconds = max(1.0, seconds)
            self.state.laptimes[index].pinned = True
            self._plan_dirty = True

    def apply_config(self, cfg: RaceConfig) -> None:
        """Swap in a new config from the options dialog.

        Laptime history rows that the driver has not pinned are re-seeded from
        the new reference, so changing the assumption in the options window
        actually takes effect.
        """
        cfg.validate()
        self.config = cfg
        for row in self.state.laptimes:
            if not row.pinned:
                row.seconds = cfg.gtd_laptime_s
        self.state.gtp_stops_remaining = cfg.gtp_stops_remaining
        self._plan_dirty = True

    def reset(self) -> None:
        """Back to the grid."""
        self.state = RaceState()
        self.state.seed(self.config)
        self._plan_dirty = True

    def toggle_mute(self) -> None:
        self.state.muted = not self.state.muted

    # ------------------------------------------------------------------ #
    # Derived snapshot
    # ------------------------------------------------------------------ #

    def derived(self, tyres_planned: bool = True) -> Derived:
        """Compute every display value.  Pure -- safe to call as often as you like."""
        cfg, st = self.config, self.state
        fpl = self.fuel_per_lap_l()

        ltp = fuel_math.laps_to_pit(st.fuel_at_lap_start_l, fpl, cfg.reserve_l)
        lap_duration = st.gtd_lap_duration_s(cfg)
        lap_remaining = max(0.0, lap_duration - (st.elapsed_s - st.gtd_lap_start_s))
        laptime = st.reference_laptime_s(cfg)

        plus_one = fuel_math.plus_one_lap_target(
            st.fuel_at_lap_start_l,
            fpl,
            cfg.reserve_l,
            cfg.plus_one_reserve_use,
            cfg.plus_one_min_ratio,
        )

        if self._plan_dirty or self._plan_cache is None:
            self._plan_cache = strategy.solve(st, cfg, fpl, tyres_planned)
            self._plan_dirty = False
        plan = self._plan_cache

        return Derived(
            time_left_s=max(0.0, cfg.race_length_s - st.elapsed_s),
            time_left_hms=prediction.format_hms(cfg.race_length_s - st.elapsed_s),
            running=st.running,
            gtd_laps_left=plan.laps_left,
            laps_to_pit=ltp,
            time_to_pit_s=fuel_math.time_to_pit_s(ltp, lap_remaining, laptime),
            time_to_pit_ms=prediction.format_ms(
                fuel_math.time_to_pit_s(ltp, lap_remaining, laptime)
            ),
            urgency=fuel_math.pit_urgency(ltp),
            fuel_left_l=st.fuel_now_l(cfg, fpl),
            fuel_per_lap_l=fpl,
            fuel_per_lap_is_measured=st.measured_fuel_per_lap_l is not None,
            plus_one_target_l=plus_one.target_l_per_lap if plus_one else None,
            plus_one_achievable=bool(plus_one and plus_one.achievable),
            gtd_lap=st.gtd_lap,
            gtp_lap=st.gtp_lap,
            gtd_phase=st.gtd_phase(cfg),
            gtp_phase=st.gtp_phase(cfg),
            catch_delta_s=prediction.catch_delta_s(st, cfg),
            plan=plan,
            reference_laptime_s=laptime,
            laptimes=[row.seconds for row in st.laptimes],
            notes=list(st.notes[-5:]),
        )

    def mark_plan_dirty(self) -> None:
        """Force the plan to be re-solved on the next snapshot."""
        self._plan_dirty = True
