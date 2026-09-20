"""Right column -- laptimes.

Hidden by default and pinned open with the button in the toolbar.  Holds the
GTD reference laptime, the last five laps (each nudgeable by 0.2 s), and the
GTP reference figures.

A nudged row is *pinned*: it survives new measurements and is not re-seeded
when the options window changes the reference laptime, because the driver
changed it on purpose.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDoubleSpinBox, QGridLayout, QLabel, QVBoxLayout, QWidget

from ..core.prediction import format_laptime
from ..core.state import LAPTIME_HISTORY
from .widgets import Divider, Panel, Stepper, caption

NUDGE_S = 0.2


class RightColumn(QWidget):
    """Laptime reference, history and GTP figures."""

    laptime_nudged = Signal(int, float)     # row index, delta seconds
    gtp_laptime_changed = Signal(float)
    gtp_pitstop_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(230)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # --- GTD reference ---------------------------------------------
        panel = Panel()
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(10, 10, 10, 10)
        inner.setSpacing(6)
        inner.addWidget(caption("GTD reference lap"))

        self.reference = QLabel("--:--.-")
        self.reference.setObjectName("Value")
        self.reference.setStyleSheet("font-size: 26px;")
        inner.addWidget(self.reference)
        inner.addWidget(Divider())
        inner.addWidget(caption("Last laps  \u00b7  \u00b1 0.2s"))

        grid = QGridLayout()
        grid.setSpacing(4)
        self.rows: list[Stepper] = []
        for i in range(LAPTIME_HISTORY):
            row = Stepper("--:--.-")
            row.stepped.connect(
                lambda direction, index=i: self.laptime_nudged.emit(
                    index, direction * NUDGE_S
                )
            )
            self.rows.append(row)
            grid.addWidget(row, i, 0)
        inner.addLayout(grid)
        layout.addWidget(panel)

        # --- GTP figures ------------------------------------------------
        gtp_panel = Panel()
        gtp_inner = QVBoxLayout(gtp_panel)
        gtp_inner.setContentsMargins(10, 10, 10, 10)
        gtp_inner.setSpacing(6)
        gtp_inner.addWidget(caption("GTP lap time"))

        self.gtp_laptime = QDoubleSpinBox()
        self.gtp_laptime.setRange(10.0, 600.0)
        self.gtp_laptime.setDecimals(1)
        self.gtp_laptime.setSingleStep(0.1)
        self.gtp_laptime.setSuffix(" s")
        self.gtp_laptime.valueChanged.connect(self.gtp_laptime_changed.emit)
        gtp_inner.addWidget(self.gtp_laptime)

        gtp_inner.addWidget(caption("GTP pit stop"))
        self.gtp_pitstop = QDoubleSpinBox()
        self.gtp_pitstop.setRange(0.0, 600.0)
        self.gtp_pitstop.setDecimals(0)
        self.gtp_pitstop.setSuffix(" s")
        self.gtp_pitstop.valueChanged.connect(self.gtp_pitstop_changed.emit)
        gtp_inner.addWidget(self.gtp_pitstop)
        layout.addWidget(gtp_panel)

        layout.addStretch(1)

    # ------------------------------------------------------------------ #

    def seed_from_config(self, cfg) -> None:
        """Push config values in without re-emitting valueChanged."""
        for box, value in (
            (self.gtp_laptime, cfg.gtp_laptime_s),
            (self.gtp_pitstop, cfg.gtp_pitstop_s),
        ):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def render_windowed(self, d) -> None:
        self.reference.setText(format_laptime(d.reference_laptime_s))
        for row, seconds in zip(self.rows, d.laptimes):
            row.set_text(format_laptime(seconds))
