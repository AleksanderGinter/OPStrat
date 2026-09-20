"""Strategy solver and engine behaviour.

The solver is where the spec's own rules had to be reconciled, so the intent
of each tier is pinned down here.
"""

from __future__ import annotations

import pytest

from imsa_strategy.core import pitstop, strategy
from imsa_strategy.core.config import RaceConfig
from imsa_strategy.core.engine import Engine


def _config(**overrides) -> RaceConfig:
    base = dict(
        race_length_s=7200,
        tank_size_l=100.0,
        fuel_per_lap_l=3.1,
        reserve_l=2.0,
        full_tank_fill_s=40.0,
        tyre_change_s=20.0,
        pit_delta_s=45.0,
        gtd_laptime_s=100.0,
        gtp_laptime_s=94.0,
        gtp_pitstop_s=55.0,
        gtp_stops_remaining=1,
    )
    base.update(overrides)
    return RaceConfig(**base)


def _engine(**overrides) -> Engine:
    engine = Engine(_config(**overrides))
    engine.start()
    return engine


# --------------------------------------------------------------------- #
# Plan shape
# --------------------------------------------------------------------- #

def test_no_stops_when_the_fuel_aboard_reaches_the_flag():
    engine = _engine(race_length_s=600)     # ~7 laps, full tank
    plan = strategy.solve(engine.state, engine.config, 3.1)
    assert plan.stop_count == 0


def test_two_hour_race_plans_two_stops():
    engine = _engine()
    plan = strategy.solve(engine.state, engine.config, 3.1)
    assert plan.stop_count == 2
    assert plan.converged


def test_no_stop_fill_exceeds_the_tank():
    engine = _engine()
    plan = strategy.solve(engine.state, engine.config, 3.1)
    for stop in plan.stops:
        assert stop.fuel_l <= engine.config.tank_size_l + 1e-9


def test_planned_fills_cover_the_laps_they_claim():
    engine = _engine()
    plan = strategy.solve(engine.state, engine.config, 3.1)
    for stop in plan.stops:
        needed = stop.laps_covered * 3.1 + engine.config.reserve_l
        assert stop.fuel_l >= needed - 1e-6


def test_plan_covers_every_remaining_lap():
    engine = _engine()
    plan = strategy.solve(engine.state, engine.config, 3.1)
    covered = plan.laps_on_current_fuel + sum(s.laps_covered for s in plan.stops)
    assert covered >= plan.laps_left


# --------------------------------------------------------------------- #
# The tyre-window rule
# --------------------------------------------------------------------- #

def test_neither_of_the_last_two_stops_wastes_the_tyre_window():
    """The reason the penultimate stop is not simply minimised.

    Fuel poured while the tyres are being changed is free.  A fill shorter
    than the tyre change therefore throws away time that is being spent
    anyway -- so the penultimate stop is the smallest fill that still fills
    the window, not the smallest fill full stop.
    """
    engine = _engine()
    cfg = engine.config
    plan = strategy.solve(engine.state, cfg, 3.1)
    tyre_equiv = pitstop.tyre_equivalent_fuel_l(cfg)

    assert plan.stop_count == 2
    for stop in plan.stops:
        assert stop.fuel_l >= tyre_equiv - 1e-6


def test_the_tyre_window_split_is_not_slower_than_minimising_the_penultimate():
    """Guards the fix: the naive 'smallest penultimate' split loses time."""
    engine = _engine()
    cfg = engine.config
    plan = strategy.solve(engine.state, cfg, 3.1)
    chosen = sum(s.total_time_s for s in plan.stops)

    # Same total fuel, but shifted so the penultimate fill is as small as
    # possible -- which drops it under the tyre change.
    total_laps = sum(s.laps_covered for s in plan.stops)
    stint_max = int((cfg.tank_size_l - cfg.reserve_l) // 3.1)
    naive_final = min(stint_max, total_laps - 1)
    naive = sum(
        pitstop.build_stop(cfg, laps * 3.1 + cfg.reserve_l).total_time_s
        for laps in (total_laps - naive_final, naive_final)
    )
    assert chosen <= naive + 1e-6


def test_short_final_fill_is_raised_to_the_tyre_window():
    """A single splash-and-dash gets topped up, because the fuel is free."""
    engine = _engine(race_length_s=4200)
    plan = strategy.solve(engine.state, engine.config, 3.1, tyres_planned=True)
    if plan.stop_count == 1:
        final = plan.stops[-1]
        assert final.fuel_l >= pitstop.tyre_equivalent_fuel_l(engine.config) - 1e-6


def test_solver_terminates_on_a_pathological_config():
    """Bounded fixed point: never hangs, even when the numbers fight."""
    engine = _engine(pit_delta_s=300.0, full_tank_fill_s=200.0, tank_size_l=40.0)
    plan = strategy.solve(engine.state, engine.config, 3.1)
    assert plan.stop_count >= 0     # returning at all is the assertion


# --------------------------------------------------------------------- #
# Engine events
# --------------------------------------------------------------------- #

def test_pit_adds_time_to_the_current_lap_and_fuel_to_the_tank():
    engine = _engine()
    engine.tick(3000)                               # burn most of the tank
    before_fuel = engine.state.fuel_at_lap_start_l
    before_lap = engine.state.gtd_lap

    stop = engine.commit_pit(40.0, tyres=True, repair_s=0.0)

    assert engine.state.fuel_at_lap_start_l == pytest.approx(before_fuel + 40.0)
    assert engine.state.gtd_lap_extra_s == pytest.approx(stop.total_time_s)
    assert engine.state.gtd_lap == before_lap       # the lap has not rolled over
    assert engine.state.stops_done == 1


def test_pit_cannot_overfill_the_tank():
    engine = _engine()
    engine.tick(300)
    stop = engine.commit_pit(500.0)
    assert engine.state.fuel_at_lap_start_l <= engine.config.tank_size_l + 1e-9
    assert stop.fuel_l < 500.0


def test_fuel_sync_measures_consumption_between_two_entries():
    engine = _engine()
    engine.tick(0.0)
    engine.fuel_sync(100.0)          # open the window on lap 1
    engine.tick(1000.0)              # 10 laps
    engine.fuel_sync(65.0)           # 35 L over 10 laps
    assert engine.state.measured_fuel_per_lap_l == pytest.approx(3.5)
    assert engine.fuel_per_lap_l() == pytest.approx(3.5)


def test_fuel_sync_ignores_an_impossible_entry():
    engine = _engine()
    engine.fuel_sync(50.0)
    engine.tick(1000.0)
    engine.fuel_sync(80.0)           # more fuel than before, with no stop
    assert engine.state.measured_fuel_per_lap_l is None


def test_gtd_sync_rounds_to_the_nearer_whole_lap():
    engine = _engine()
    engine.tick(90.0)                # 90% around the lap
    engine.gtd_sync()
    assert engine.state.gtd_lap == 2                     # rounded up
    assert engine.state.gtd_phase(engine.config) == pytest.approx(0.0)

    engine2 = _engine()
    engine2.tick(20.0)               # only 20% around
    engine2.gtd_sync()
    assert engine2.state.gtd_lap == 1                    # rounded down


def test_gtp_sync_zeroes_the_delta():
    engine = _engine()
    engine.tick(450.0)
    engine.gtp_sync()
    derived = engine.derived()
    assert derived.catch_delta_s == pytest.approx(0.0, abs=1e-6)


def test_gtp_pitted_does_not_make_laps_left_jump():
    """The stop was already carried as padding, so converting it is quiet."""
    engine = _engine()
    engine.tick(1800)
    before = engine.derived().gtd_laps_left
    engine.gtp_pitted()
    after = engine.derived().gtd_laps_left
    assert abs(after - before) <= 1
    assert engine.state.gtp_stops_remaining == 0


def test_lap_counter_cannot_go_below_one():
    engine = _engine()
    for _ in range(10):
        engine.adjust_gtd_lap(-1)
    assert engine.state.gtd_lap == 1


def test_laptime_nudges_are_pinned_and_survive_a_config_change():
    engine = _engine()
    engine.nudge_laptime(0, +0.2)
    pinned = engine.state.laptimes[0].seconds
    engine.apply_config(_config(gtd_laptime_s=105.0))
    assert engine.state.laptimes[0].seconds == pytest.approx(pinned)
    assert engine.state.laptimes[1].seconds == pytest.approx(105.0)


def test_engine_never_hangs_advancing_laps():
    """A clamped lap duration keeps the tick loop bounded."""
    engine = _engine()
    for row in engine.state.laptimes:
        row.seconds = 1.0
    engine.tick(5000.0)              # would be 5000 laps without the cap
    assert engine.state.gtd_lap >= 1


def test_paused_clock_freezes_everything():
    engine = _engine()
    engine.pause()
    before = engine.derived()
    engine.tick(600.0)
    after = engine.derived()
    assert after.time_left_s == pytest.approx(before.time_left_s)
    assert after.gtd_phase == pytest.approx(before.gtd_phase)
