"""Unit tests for the fuel, pit and prediction maths.

These are the calculations where an off-by-one costs a race, so the boundaries
are tested explicitly rather than by example.
"""

from __future__ import annotations

import pytest

from imsa_strategy.core import fuel, pitstop, prediction
from imsa_strategy.core.config import ConfigError, RaceConfig
from imsa_strategy.core.engine import Engine


# --------------------------------------------------------------------- #
# Fuel
# --------------------------------------------------------------------- #

def test_laps_possible_respects_the_reserve():
    # 20 L aboard, 2 L reserve, 3 L/lap -> 18 usable -> 6 laps
    assert fuel.laps_possible(20.0, 3.0, 2.0) == 6
    # One drop short of the seventh lap
    assert fuel.laps_possible(22.9, 3.0, 2.0) == 6
    assert fuel.laps_possible(23.0, 3.0, 2.0) == 7


def test_laps_to_pit_boundaries():
    """0 means pit at the end of this lap; 1 means at the end of the next."""
    reserve, per_lap = 2.0, 3.0

    # Exactly enough for this lap and the reserve: pit at the end of this lap.
    assert fuel.laps_to_pit(5.0, per_lap, reserve) == 0
    # Enough for this lap plus one more: pit at the end of the next lap.
    assert fuel.laps_to_pit(8.0, per_lap, reserve) == 1
    # Comfortable.
    assert fuel.laps_to_pit(20.0, per_lap, reserve) == 5
    # Cannot even finish this lap on usable fuel.
    assert fuel.laps_to_pit(1.0, per_lap, reserve) == -1


def test_pit_urgency_mapping():
    assert fuel.pit_urgency(3) is fuel.PitUrgency.NONE
    assert fuel.pit_urgency(1) is fuel.PitUrgency.NEXT_LAP     # yellow
    assert fuel.pit_urgency(0) is fuel.PitUrgency.THIS_LAP     # red
    assert fuel.pit_urgency(-1) is fuel.PitUrgency.OVERDUE


def test_plus_one_target_dips_into_part_of_the_reserve():
    # 20 L aboard, 3 L/lap, 2 L reserve -> 5 laps to pit, stint of 6.
    target = fuel.plus_one_lap_target(20.0, 3.0, 2.0, reserve_use=0.70, min_ratio=0.85)
    assert target is not None
    assert target.extended_stint_laps == 7
    # available = 20 - 2*0.30 = 19.4, over 7 laps
    assert target.target_l_per_lap == pytest.approx(19.4 / 7)
    # 2.77 vs 3.00 average is a 7.7% save -> achievable
    assert target.achievable


def test_plus_one_target_marked_impossible_when_save_is_too_deep():
    # Only just enough for one more lap: stretching to two needs a huge save.
    target = fuel.plus_one_lap_target(5.0, 3.0, 2.0, reserve_use=0.70, min_ratio=0.85)
    assert target is not None
    assert not target.achievable


def test_measure_fuel_per_lap_excludes_out_laps():
    # 60 L at the start, 30 L added, 40 L now, over 12 laps of which 1 was an out-lap.
    result = fuel.measure_fuel_per_lap(60.0, 40.0, 30.0, laps_in_window=12, out_laps=1)
    assert result == pytest.approx(50.0 / 11)


def test_measure_fuel_per_lap_rejects_nonsense():
    assert fuel.measure_fuel_per_lap(60.0, 70.0, 0.0, 5) is None      # gained fuel
    assert fuel.measure_fuel_per_lap(60.0, 40.0, 0.0, 0) is None      # no laps
    assert fuel.measure_fuel_per_lap(60.0, 40.0, 0.0, 2, out_laps=2) is None


# --------------------------------------------------------------------- #
# Pit stop
# --------------------------------------------------------------------- #

def test_fill_time_scales_linearly():
    cfg = RaceConfig(tank_size_l=100.0, full_tank_fill_s=40.0)
    assert pitstop.fill_time_s(100.0, cfg) == pytest.approx(40.0)
    assert pitstop.fill_time_s(50.0, cfg) == pytest.approx(20.0)
    assert pitstop.fill_time_s(0.0, cfg) == 0.0


def test_service_is_concurrent_and_repairs_are_serial():
    cfg = RaceConfig(
        tank_size_l=100.0, full_tank_fill_s=40.0, tyre_change_s=20.0, pit_delta_s=45.0
    )
    # 60 L takes 24s, longer than the 20s tyre change.
    stop = pitstop.build_stop(cfg, 60.0, tyres=True, repair_s=10.0)
    assert stop.service_time_s == pytest.approx(24.0 + 10.0)
    assert stop.total_time_s == pytest.approx(45.0 + 34.0)
    assert not stop.warn_fuel_shorter_than_tyres


def test_tyre_limited_stop_warns_and_reports_free_fuel_time():
    cfg = RaceConfig(tank_size_l=100.0, full_tank_fill_s=40.0, tyre_change_s=20.0)
    stop = pitstop.build_stop(cfg, 25.0, tyres=True)   # 10s of fill
    assert stop.warn_fuel_shorter_than_tyres
    assert stop.free_fuel_window_s == pytest.approx(10.0)
    assert pitstop.tyre_equivalent_fuel_l(cfg) == pytest.approx(50.0)


# --------------------------------------------------------------------- #
# Race end
# --------------------------------------------------------------------- #

def _engine_at(elapsed_s: float, **overrides) -> Engine:
    settings = dict(
        race_length_s=7200,
        gtd_laptime_s=100.0,
        gtp_laptime_s=94.0,
        gtp_stops_remaining=0,
    )
    settings.update(overrides)
    cfg = RaceConfig(**settings)
    engine = Engine(cfg)
    engine.start()
    engine.tick(elapsed_s)
    return engine


def test_flag_is_the_first_gtp_crossing_after_the_clock():
    engine = _engine_at(0.0)
    flag = prediction.flag_time_s(engine.state, engine.config)
    # 94s laps from zero: the first crossing at or after 7200 is 94 * 77 = 7238
    assert flag == pytest.approx(7238.0)


def test_gtp_stops_delay_the_flag():
    engine = _engine_at(0.0, gtp_pitstop_s=55.0)
    engine.state.gtp_stops_remaining = 1
    flag = prediction.flag_time_s(engine.state, engine.config)
    assert flag > 7238.0


def test_laps_left_is_not_simply_time_over_laptime():
    """The naive formula gives 72; the correct answer here is 73."""
    engine = _engine_at(0.0)
    end = prediction.predict_end(engine.state, engine.config)
    naive = engine.config.race_length_s / engine.config.gtd_laptime_s
    assert naive == pytest.approx(72.0)
    assert end.gtd_laps_left == 73


def test_our_pit_time_can_cost_a_lap():
    engine = _engine_at(0.0)
    without = prediction.predict_end(engine.state, engine.config, our_pit_time_s=0.0)
    with_stops = prediction.predict_end(
        engine.state, engine.config, our_pit_time_s=200.0
    )
    assert with_stops.gtd_laps_left < without.gtd_laps_left


def test_catch_delta_is_none_when_gtp_is_not_faster():
    engine = _engine_at(0.0, gtp_laptime_s=110.0)   # slower than our 100s
    assert prediction.catch_delta_s(engine.state, engine.config) is None


def test_catch_delta_closes_at_the_right_rate():
    engine = _engine_at(0.0)
    engine.gtp_sync()                    # dots together, delta zero
    assert prediction.catch_delta_s(engine.state, engine.config) == pytest.approx(0.0, abs=1e-6)


def test_format_helpers():
    assert prediction.format_hms(3661) == "01:01:01"
    assert prediction.format_hms(-5) == "00:00:00"
    assert prediction.format_ms(95) == "01:35"
    assert prediction.format_laptime(94.3) == "1:34.3"


# --------------------------------------------------------------------- #
# Config validation
# --------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "kwargs",
    [
        {"tank_size_l": 0.0},
        {"fuel_per_lap_l": 0.0},
        {"reserve_l": 200.0},
        {"gtd_laptime_s": 0.0},
        {"refresh_window_s": 7},
        {"tank_size_l": 10.0, "fuel_per_lap_l": 9.0, "reserve_l": 5.0},
    ],
)
def test_invalid_configs_are_rejected(kwargs):
    with pytest.raises(ConfigError):
        RaceConfig(**kwargs).validate()


def test_config_round_trips_through_json(tmp_path):
    cfg = RaceConfig(race_length_s=9000, fuel_per_lap_l=2.85)
    path = tmp_path / "cfg.json"
    cfg.save(path)
    assert RaceConfig.load(path) == cfg


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text("{not json", encoding="utf-8")
    assert RaceConfig.load(path) == RaceConfig()
