"""Middle column -- track map and the fuel strategy overview.

The strategy boxes are rebuilt whenever the number of stops changes, and
updated in place otherwise, so a stop disappearing mid-race does not leave a
stale box on screen.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .track_map import TrackMap
from .widgets import Panel, Stepper, caption


class StopBox(Panel):
    """One projected stop: fuel, laps it covers, and what it costs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = QLabel("Stop")
        self.title.setObjectName("Caption")

        self.fuel = QLabel("--")
        self.fuel.setObjectName("Value")
        self.fuel.setStyleSheet("font-size: 24px;")

        self.detail = QLabel("--")
        self.detail.setObjectName("Caption")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(1)
        layout.addWidget(self.title)
        layout.addWidget(self.fuel)
        layout.addWidget(self.detail)

    def render(self, stop) -> None:
        self.title.setText("Final stop" if stop.is_final else f"Stop {stop.index}")
        self.fuel.setText(f"{stop.fuel_l:.1f} L")
        self.fuel.setStyleSheet(
            f"font-size: 24px; color: {theme.GTP if stop.is_final else theme.TEXT};"
        )
        note = f"  \u00b7  {stop.note}" if stop.note else ""
        self.detail.setText(
            f"{stop.laps_covered} laps  \u00b7  {stop.total_time_s:.0f}s lost{note}"
        )


class MiddleColumn(QWidget):
    """Track map, sync controls and the stop plan."""

    gtd_sync = Signal()
    gtp_sync = Signal()
    gtp_pitted = Signal()
    gtd_lap_stepped = Signal(int)
    gtp_lap_stepped = Signal(int)
    gtp_stops_stepped = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # --- sync line -------------------------------------------------
        self.gtd_sync_button = QPushButton("GTD sync \u2014 on the line")
        self.gtd_sync_button.setToolTip(
            "Press as you cross the line. Snaps the dot to the line, rounds the "
            "lap counter to the nearer whole lap and records the lap time."
        )
        self.gtd_sync_button.clicked.connect(self.gtd_sync.emit)
        layout.addWidget(self.gtd_sync_button)

        # --- map -------------------------------------------------------
        self.map = TrackMap()
        layout.addWidget(self.map, 1)

        # --- lap counter steppers -------------------------------------
        steppers = QGridLayout()
        steppers.setSpacing(6)

        self.gtd_stepper = Stepper("GTD lap 1")
        self.gtd_stepper.stepped.connect(self.gtd_lap_stepped.emit)
        self.gtp_stepper = Stepper("GTP lap 1")
        self.gtp_stepper.stepped.connect(self.gtp_lap_stepped.emit)
        self.gtp_stops_stepper = Stepper("GTP stops left 1")
        self.gtp_stops_stepper.stepped.connect(self.gtp_stops_stepped.emit)

        steppers.addWidget(self.gtd_stepper, 0, 0)
        steppers.addWidget(self.gtp_stepper, 0, 1)
        steppers.addWidget(self.gtp_stops_stepper, 1, 0, 1, 2)
        layout.addLayout(steppers)

        # --- GTP controls ---------------------------------------------
        gtp_row = QHBoxLayout()
        gtp_row.setSpacing(6)
        self.gtp_sync_button = QPushButton("GTP sync \u2014 alongside us")
        self.gtp_sync_button.setToolTip("Puts the GTP dot on ours and zeroes the delta.")
        self.gtp_sync_button.clicked.connect(self.gtp_sync.emit)
        self.gtp_pit_button = QPushButton("GTP pitted")
        self.gtp_pit_button.setToolTip(
            "Banks a real GTP stop and drops one from the expectation, so the "
            "laps-left prediction does not jump."
        )
        self.gtp_pit_button.clicked.connect(self.gtp_pitted.emit)
        gtp_row.addWidget(self.gtp_sync_button, 1)
        gtp_row.addWidget(self.gtp_pit_button)
        layout.addLayout(gtp_row)

        # --- strategy boxes -------------------------------------------
        layout.addWidget(caption("Fuel strategy"))
        self.boxes_row = QHBoxLayout()
        self.boxes_row.setSpacing(6)
        holder = QWidget()
        holder.setLayout(self.boxes_row)
        layout.addWidget(holder)

        self.plan_note = QLabel("")
        self.plan_note.setObjectName("Caption")
        self.plan_note.setWordWrap(True)
        layout.addWidget(self.plan_note)

        self._boxes: list[StopBox] = []

    # ------------------------------------------------------------------ #

    def render_fast(self, d, clockwise: bool) -> None:
        self.map.update_snapshot(
            d.gtd_phase, d.gtp_phase, d.gtd_lap, d.gtp_lap, d.catch_delta_s, clockwise
        )

    def render_windowed(self, d, gtp_stops_remaining: int) -> None:
        self.gtd_stepper.set_text(f"GTD lap {d.gtd_lap}")
        self.gtp_stepper.set_text(f"GTP lap {d.gtp_lap}")
        self.gtp_stops_stepper.set_text(f"GTP stops left {gtp_stops_remaining}")
        self._render_plan(d.plan)

    def _render_plan(self, plan) -> None:
        if plan is None:
            return

        # Rebuild only when the count changes; otherwise update in place.
        while len(self._boxes) < plan.stop_count:
            box = StopBox()
            self._boxes.append(box)
            self.boxes_row.addWidget(box)
        while len(self._boxes) > plan.stop_count:
            box = self._boxes.pop()
            self.boxes_row.removeWidget(box)
            box.deleteLater()

        for box, stop in zip(self._boxes, plan.stops):
            box.render(stop)

        if plan.stop_count == 0:
            self.plan_note.setText(
                "No more stops needed \u2014 there is enough fuel aboard to reach the flag."
            )
        else:
            note = (
                f"{plan.stop_count} stop(s) left \u00b7 "
                f"{plan.total_pit_time_s:.0f}s total \u00b7 "
                f"{plan.laps_on_current_fuel} laps on what is aboard"
            )
            if plan.warnings:
                note += "\n" + "\n".join(plan.warnings)
            self.plan_note.setText(note)

    def suggested_next_fuel(self, plan) -> float | None:
        """Fuel for the next stop, used to pre-fill the pit builder."""
        if plan and plan.stops:
            return plan.stops[0].fuel_l
        return None
