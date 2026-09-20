"""Pre-race options.

Everything here comes from free practice and holds as the working assumption
until the driver refines it live.  The dialog validates before it closes, so
an impossible configuration (reserve bigger than the tank, zero laptime) never
reaches the engine.
"""

from __future__ import annotations

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QMessageBox,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
)

from ..core.config import ConfigError, RaceConfig
from .widgets import Divider, caption


class OptionsDialog(QDialog):
    """Edits a :class:`RaceConfig`."""

    def __init__(self, config: RaceConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Race setup")
        self.setMinimumWidth(420)
        self._config = config

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        form = QFormLayout()
        form.setSpacing(6)

        # --- race -------------------------------------------------------
        layout.addWidget(caption("Race"))
        self.race_length = QTimeEdit()
        self.race_length.setDisplayFormat("HH:mm:ss")
        self.race_length.setTime(_to_qtime(config.race_length_s))
        form.addRow("Race length", self.race_length)

        self.direction = QComboBox()
        self.direction.addItems(["Clockwise", "Anticlockwise"])
        self.direction.setCurrentIndex(0 if config.track_clockwise else 1)
        form.addRow("Track direction", self.direction)

        self.refresh = QComboBox()
        self.refresh.addItems(["5 s", "10 s"])
        self.refresh.setCurrentIndex(0 if config.refresh_window_s == 5 else 1)
        self.refresh.setToolTip(
            "How often the strategy numbers refresh.\n"
            "The clock, the track map and the pit warning always update live."
        )
        form.addRow("Refresh window", self.refresh)
        layout.addLayout(form)
        layout.addWidget(Divider())

        # --- fuel -------------------------------------------------------
        layout.addWidget(caption("Fuel"))
        fuel_form = QFormLayout()
        fuel_form.setSpacing(6)
        self.tank = _spin(config.tank_size_l, 1.0, 500.0, 1, " L")
        self.fuel_per_lap = _spin(config.fuel_per_lap_l, 0.1, 100.0, 2, " L")
        self.reserve = _spin(config.reserve_l, 0.0, 100.0, 1, " L")
        self.reserve_use = _spin(config.plus_one_reserve_use * 100, 0, 100, 0, " %")
        self.min_ratio = _spin(config.plus_one_min_ratio * 100, 1, 100, 0, " %")
        self.min_ratio.setToolTip(
            "Below this fraction of your average, a fuel save is treated as "
            "impossible and the +1 lap target greys out."
        )
        fuel_form.addRow("Tank size", self.tank)
        fuel_form.addRow("Fuel per lap", self.fuel_per_lap)
        fuel_form.addRow("Reserve", self.reserve)
        fuel_form.addRow("Reserve usable for +1 lap", self.reserve_use)
        fuel_form.addRow("Minimum achievable save", self.min_ratio)
        layout.addLayout(fuel_form)
        layout.addWidget(Divider())

        # --- pit --------------------------------------------------------
        layout.addWidget(caption("Pit stop"))
        pit_form = QFormLayout()
        pit_form.setSpacing(6)
        self.fill_time = _spin(config.full_tank_fill_s, 1.0, 600.0, 0, " s")
        self.tyre_time = _spin(config.tyre_change_s, 0.0, 600.0, 0, " s")
        self.pit_delta = _spin(config.pit_delta_s, 0.0, 600.0, 0, " s")
        pit_form.addRow("Time to fill a full tank", self.fill_time)
        pit_form.addRow("Tyre change", self.tyre_time)
        pit_form.addRow("Drive-through delta", self.pit_delta)
        layout.addLayout(pit_form)
        layout.addWidget(Divider())

        # --- laptimes ---------------------------------------------------
        layout.addWidget(caption("Reference lap times"))
        lap_form = QFormLayout()
        lap_form.setSpacing(6)
        self.gtd_lap = _spin(config.gtd_laptime_s, 10.0, 600.0, 1, " s")
        self.gtp_lap = _spin(config.gtp_laptime_s, 10.0, 600.0, 1, " s")
        self.gtp_pit = _spin(config.gtp_pitstop_s, 0.0, 600.0, 0, " s")
        self.gtp_stops = QSpinBox()
        self.gtp_stops.setRange(0, 30)
        self.gtp_stops.setValue(config.gtp_stops_remaining)
        self.gtp_stops.setToolTip(
            "Stops the GTP leader is still expected to make. The prediction "
            "carries them from the start so laps left does not jump when they pit."
        )
        lap_form.addRow("GTD lap time", self.gtd_lap)
        lap_form.addRow("GTP lap time", self.gtp_lap)
        lap_form.addRow("GTP pit stop", self.gtp_pit)
        lap_form.addRow("GTP stops remaining", self.gtp_stops)
        layout.addLayout(lap_form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, Qt.Horizontal
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ #

    def _accept(self) -> None:
        try:
            config = self.result_config()
            config.validate()
        except ConfigError as exc:
            QMessageBox.warning(self, "Check the setup", str(exc))
            return
        self._config = config
        self.accept()

    def result_config(self) -> RaceConfig:
        time = self.race_length.time()
        return RaceConfig(
            race_length_s=time.hour() * 3600 + time.minute() * 60 + time.second(),
            track_clockwise=self.direction.currentIndex() == 0,
            refresh_window_s=5 if self.refresh.currentIndex() == 0 else 10,
            tank_size_l=self.tank.value(),
            fuel_per_lap_l=self.fuel_per_lap.value(),
            reserve_l=self.reserve.value(),
            plus_one_reserve_use=self.reserve_use.value() / 100.0,
            plus_one_min_ratio=self.min_ratio.value() / 100.0,
            full_tank_fill_s=self.fill_time.value(),
            tyre_change_s=self.tyre_time.value(),
            pit_delta_s=self.pit_delta.value(),
            gtd_laptime_s=self.gtd_lap.value(),
            gtp_laptime_s=self.gtp_lap.value(),
            gtp_pitstop_s=self.gtp_pit.value(),
            gtp_stops_remaining=self.gtp_stops.value(),
        )

    @property
    def config(self) -> RaceConfig:
        return self._config


def _spin(value, lo, hi, decimals, suffix) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    box.setSingleStep(10 ** -decimals if decimals else 1)
    box.setValue(value)
    return box


def _to_qtime(seconds: int) -> QTime:
    return QTime(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
