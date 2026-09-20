"""Race-end prediction.

The rule being modelled: the race ends when the **GTP leader** crosses the line
after the clock has expired.  Every other car then finishes on its own next
crossing.  So our laps left is a two-stage calculation:

    1. When does the GTP leader take the flag?   -> ``flag_time_s``
    2. How many more times do we cross the line
       up to and including the first crossing
       at or after that moment?                  -> ``gtd_laps_left``

This is why ``time_left / laptime`` is wrong: it ignores where both cars are on
the circle, and can be out by well over a lap.

GTP pit stops are handled with a padding model.  Every stop we still expect GTP
to make is assumed to happen before the flag, so it delays every future GTP
crossing by the same total.  Pressing "GTP pitted" converts an expected stop
into a real one (added to GTP's current lap) and decrements the counter, so the
prediction does not jump.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Hard iteration ceilings.  Every loop in this module is bounded: a zero or
# negative laptime that slipped past validation must not hang the UI thread.
_MAX_ITER = 100_000


@dataclass
class EndOfRace:
    """Result of the race-end calculation."""

    time_left_s: float          # on the race clock
    flag_time_s: float          # elapsed-race-time at which GTP takes the flag
    gtd_laps_left: int          # crossings remaining for us, including the last one
    gtd_finish_time_s: float    # elapsed-race-time at which we take the flag


def next_crossing_s(lap_start_s: float, lap_duration_s: float) -> float:
    """Race-clock time of this car's next line crossing."""
    return lap_start_s + max(0.1, lap_duration_s)


def flag_time_s(state, cfg) -> float:
    """When the GTP leader crosses the line after the clock expires."""
    laptime = max(0.1, cfg.gtp_laptime_s)
    pad = max(0, state.gtp_stops_remaining) * max(0.0, cfg.gtp_pitstop_s)

    first = next_crossing_s(state.gtp_lap_start_s, state.gtp_lap_duration_s(cfg))
    # All future crossings shift by `pad`, so solve against a shifted target.
    target = cfg.race_length_s - pad

    if first >= target:
        base = first
    else:
        laps_needed = math.ceil((target - first) / laptime - 1e-9)
        laps_needed = min(laps_needed, _MAX_ITER)
        base = first + laps_needed * laptime
    return base + pad


def gtd_laps_left(state, cfg, flag_s: float, our_pit_time_s: float = 0.0) -> tuple[int, float]:
    """Crossings we have left, and when the last one happens.

    ``our_pit_time_s`` is the total time we still expect to lose in the pits;
    it pushes all of our future crossings later and can cost us a lap.
    """
    laptime = max(0.1, state.reference_laptime_s(cfg))
    first = next_crossing_s(state.gtd_lap_start_s, state.gtd_lap_duration_s(cfg))
    first += our_pit_time_s

    if first >= flag_s:
        return 1, first

    laps_after = math.ceil((flag_s - first) / laptime - 1e-9)
    laps_after = min(laps_after, _MAX_ITER)
    finish = first + laps_after * laptime
    return 1 + int(laps_after), finish


def predict_end(state, cfg, our_pit_time_s: float = 0.0) -> EndOfRace:
    """Full race-end picture."""
    flag = flag_time_s(state, cfg)
    laps, finish = gtd_laps_left(state, cfg, flag, our_pit_time_s)
    return EndOfRace(
        time_left_s=max(0.0, cfg.race_length_s - state.elapsed_s),
        flag_time_s=flag,
        gtd_laps_left=laps,
        gtd_finish_time_s=finish,
    )


def catch_delta_s(state, cfg) -> float | None:
    """Seconds until the GTP leader catches us on track.

    Measures the on-track gap from GTP forwards to us, then divides by the
    closing rate.  Returns ``None`` when GTP is not actually faster (closing
    rate zero or negative), which the UI shows as "--" rather than dividing by
    zero or displaying an absurd number.
    """
    t_gtd = max(0.1, state.reference_laptime_s(cfg))
    t_gtp = max(0.1, cfg.gtp_laptime_s)

    closing_laps_per_s = (1.0 / t_gtp) - (1.0 / t_gtd)
    if closing_laps_per_s <= 1e-9:
        return None

    gap_laps = (state.gtd_phase(cfg) - state.gtp_phase(cfg)) % 1.0
    return gap_laps / closing_laps_per_s


def format_hms(seconds: float) -> str:
    """Seconds -> hh:mm:ss, clamped at zero."""
    s = max(0, int(round(seconds)))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def format_ms(seconds: float) -> str:
    """Seconds -> mm:ss, clamped at zero."""
    s = max(0, int(round(seconds)))
    return f"{s // 60:02d}:{s % 60:02d}"


def format_laptime(seconds: float) -> str:
    """Seconds -> m:ss.t, the way a laptime is normally read."""
    if seconds <= 0:
        return "--:--.-"
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes}:{rest:04.1f}"
