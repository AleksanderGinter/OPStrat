"""Left column -- the strategy column.

Four rows, top to bottom:

1. Race clock + predicted laps left
2. Time and laps to the pit window (with the flash warning)
3. Fuel: left, per lap, the +1 lap save target, and the manual sync
4. The pit stop builder

This widget emits commands and renders snapshots.  It never reads the engine
directly, so it can be driven from a test or a replay with fabricated data.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.fuel import PitUrgency
from . import theme
from .widgets import Divider, FlashingReadout, Panel, Readout, caption


class LeftColumn(QWidget):
    """Clock, pit window, fuel and the pit stop builder."""

    start_toggled = Signal()
    mute_toggled = Signal()
    fuel_synced = Signal(float)
    pit_committed = Signal(float, bool, float)   # litres, tyres, repair seconds
    pit_inputs_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_clock_row())
        layout.addWidget(self._build_pit_window_row())
        layout.addWidget(self._build_fuel_row())
        layout.addWidget(self._build_pitstop_row(), 1)

    # ------------------------------------------------------------------ #
    # Row 1 -- clock
    # ------------------------------------------------------------------ #

    def _build_clock_row(self) -> QWidget:
        panel = Panel()
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(8)

        self.start_button = QPushButton("Start race")
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self.start_toggled.emit)

        self.time_left = Readout("Time left", "00:00:00", value_px=40)
        self.laps_left = Readout("Laps left (predicted)", "--", value_px=40)

        grid.addWidget(self.start_button, 0, 0, 1, 2)
        grid.addWidget(self.time_left, 1, 0)
        grid.addWidget(self.laps_left, 1, 1)
        return panel

    # ------------------------------------------------------------------ #
    # Row 2 -- pit window
    # ------------------------------------------------------------------ #

    def _build_pit_window_row(self) -> QWidget:
        panel = Panel()
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(8)

        self.time_to_pit = Readout("Time to pit", "--:--", value_px=34)
        self.laps_to_pit = FlashingReadout("Laps to pit", value_px=34)

        self.mute_button = QPushButton("Mute")
        self.mute_button.setCheckable(True)
        self.mute_button.setToolTip("Silence the flashing warning; the colour stays.")
        self.mute_button.clicked.connect(self.mute_toggled.emit)

        grid.addWidget(self.time_to_pit, 0, 0)
        grid.addWidget(self.laps_to_pit, 0, 1)
        grid.addWidget(self.mute_button, 0, 2, Qt.AlignBottom)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return panel

    # ------------------------------------------------------------------ #
    # Row 3 -- fuel
    # ------------------------------------------------------------------ #

    def _build_fuel_row(self) -> QWidget:
        panel = Panel()
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(8)

        self.fuel_left = Readout("Fuel left", "--", value_px=34)
        self.fuel_per_lap = Readout("Fuel / lap", "--", value_px=28)
        self.plus_one = Readout("Fuel / lap for +1 lap", "--", value_px=28)
        self.plus_one.setToolTip(
            "Maximum consumption that would stretch the stint by one more lap.\n"
            "Greyed out when it is below the achievable fraction of your average."
        )

        self.fuel_sync_input = QDoubleSpinBox()
        self.fuel_sync_input.setRange(0.0, 500.0)
        self.fuel_sync_input.setDecimals(1)
        self.fuel_sync_input.setSingleStep(0.5)
        self.fuel_sync_input.setSuffix(" L")
        self.fuel_sync_input.setToolTip(
            "Type the fuel actually showing on the dash, then Sync.\n"
            "This re-anchors the tank and measures your real consumption."
        )

        self.fuel_sync_button = QPushButton("Sync")
        self.fuel_sync_button.clicked.connect(
            lambda: self.fuel_synced.emit(self.fuel_sync_input.value())
        )

        sync_row = QHBoxLayout()
        sync_row.setContentsMargins(0, 0, 0, 0)
        sync_row.setSpacing(6)
        sync_row.addWidget(self.fuel_sync_input, 1)
        sync_row.addWidget(self.fuel_sync_button)
        sync_holder = QWidget()
        sync_holder.setLayout(sync_row)

        grid.addWidget(self.fuel_left, 0, 0)
        grid.addWidget(self.fuel_per_lap, 0, 1)
        grid.addWidget(self.plus_one, 0, 2)
        grid.addWidget(caption("Fuel sync"), 1, 0)
        grid.addWidget(sync_holder, 2, 0, 1, 2)

        self.fuel_source = QLabel("using practice estimate")
        self.fuel_source.setObjectName("Caption")
        grid.addWidget(self.fuel_source, 2, 2)
        return panel

    # ------------------------------------------------------------------ #
    # Row 4 -- pit stop builder
    # ------------------------------------------------------------------ #

    def _build_pitstop_row(self) -> QWidget:
        panel = Panel()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        outer.addWidget(caption("Pit stop"))

        grid = QGridLayout()
        grid.setSpacing(6)

        self.pit_fuel = QDoubleSpinBox()
        self.pit_fuel.setRange(0.0, 500.0)
        self.pit_fuel.setDecimals(1)
        self.pit_fuel.setSingleStep(1.0)
        self.pit_fuel.setSuffix(" L")
        self.pit_fuel.valueChanged.connect(self.pit_inputs_changed.emit)

        self.pit_tyres = QCheckBox("Tyres")
        self.pit_tyres.setChecked(True)
        self.pit_tyres.toggled.connect(self.pit_inputs_changed.emit)

        self.pit_repair = QDoubleSpinBox()
        self.pit_repair.setRange(0.0, 600.0)
        self.pit_repair.setDecimals(0)
        self.pit_repair.setSuffix(" s")
        self.pit_repair.valueChanged.connect(self.pit_inputs_changed.emit)

        grid.addWidget(caption("Fuel in"), 0, 0)
        grid.addWidget(self.pit_fuel, 1, 0)
        grid.addWidget(caption("Repair"), 0, 1)
        grid.addWidget(self.pit_repair, 1, 1)
        grid.addWidget(self.pit_tyres, 1, 2)
        outer.addLayout(grid)

        self.pit_breakdown = QLabel("--")
        self.pit_breakdown.setObjectName("Caption")
        self.pit_breakdown.setWordWrap(True)
        outer.addWidget(self.pit_breakdown)

        self.pit_warning = QLabel("")
        self.pit_warning.setWordWrap(True)
        self.pit_warning.setStyleSheet(f"color: {theme.AMBER}; font-size: 11px;")
        outer.addWidget(self.pit_warning)

        outer.addWidget(Divider())

        self.pit_button = QPushButton("PIT")
        self.pit_button.setObjectName("Primary")
        self.pit_button.setToolTip(
            "Records the stop: adds the total time to this lap and the fuel to the tank."
        )
        self.pit_button.clicked.connect(self._emit_pit)
        outer.addWidget(self.pit_button)
        outer.addStretch(1)
        return panel

    def _emit_pit(self) -> None:
        self.pit_committed.emit(
            self.pit_fuel.value(),
            self.pit_tyres.isChecked(),
            self.pit_repair.value(),
        )

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def render_fast(self, d) -> None:
        """Values that must move smoothly: clock and fuel gauge."""
        self.time_left.set_value(d.time_left_hms)
        self.fuel_left.set_value(f"{d.fuel_left_l:.1f}")
        self.start_button.setText("Pause race" if d.running else "Start race")

    def render_windowed(self, d) -> None:
        """Values latched to the 5/10 s refresh window."""
        self.laps_left.set_value(str(d.gtd_laps_left))
        self.time_to_pit.set_value(d.time_to_pit_ms)

        laps = d.laps_to_pit
        self.laps_to_pit.set_value("PIT NOW" if laps < 0 else str(laps))

        colour = {
            PitUrgency.NONE: None,
            PitUrgency.NEXT_LAP: theme.AMBER,
            PitUrgency.THIS_LAP: theme.GTP,
            PitUrgency.OVERDUE: theme.GTP,
        }[d.urgency]
        self.laps_to_pit.set_flash(colour, muted=self.mute_button.isChecked())

        self.fuel_per_lap.set_value(f"{d.fuel_per_lap_l:.2f}")
        self.fuel_source.setText(
            "measured" if d.fuel_per_lap_is_measured else "using practice estimate"
        )

        if d.plus_one_target_l is None:
            self.plus_one.set_value("--")
            self.plus_one.set_dim(True)
        else:
            self.plus_one.set_value(f"{d.plus_one_target_l:.2f}")
            self.plus_one.set_dim(not d.plus_one_achievable)

    def render_pit_preview(self, stop) -> None:
        """Live costing of the stop currently dialled in."""
        self.pit_breakdown.setText(
            f"Fill {stop.fuel_time_s:.1f}s  \u00b7  tyres {stop.tyre_time_s:.0f}s  \u00b7  "
            f"repair {stop.repair_time_s:.0f}s  \u00b7  delta {stop.delta_s:.0f}s"
            f"   \u2192  total {stop.total_time_s:.1f}s"
        )
        if stop.warn_fuel_shorter_than_tyres:
            self.pit_warning.setText(
                f"Tyre-limited stop: {stop.free_fuel_window_s:.1f}s of fill time is "
                f"free. Taking more fuel costs nothing."
            )
        else:
            self.pit_warning.setText("")

    def suggest_fuel(self, litres: float) -> None:
        """Pre-fill the fuel box from the plan, without firing valueChanged.

        Blocking the signal here is what stops the classic Qt loop: setValue
        would otherwise emit valueChanged, which would re-render, which would
        call suggest_fuel again.
        """
        if abs(self.pit_fuel.value() - litres) < 0.05:
            return
        if self.pit_fuel.hasFocus():
            return          # never fight the driver for the keyboard
        self.pit_fuel.blockSignals(True)
        self.pit_fuel.setValue(litres)
        self.pit_fuel.blockSignals(False)
