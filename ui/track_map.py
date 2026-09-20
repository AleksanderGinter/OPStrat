"""The circular track map.

The lap is drawn as a clock face with the start/finish line at twelve o'clock.
Phase 0.0 sits on the line; the dots travel clockwise or anticlockwise
depending on the configured track direction.

The widget is a pure renderer: it holds no race state, only the last snapshot
it was told to draw.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class TrackMap(QWidget):
    """Circular position display for our GTD car and the GTP leader."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 320)

        self.gtd_phase = 0.0
        self.gtp_phase = 0.0
        self.gtd_lap = 1
        self.gtp_lap = 1
        self.delta_s: float | None = None
        self.clockwise = True

    def update_snapshot(
        self,
        gtd_phase: float,
        gtp_phase: float,
        gtd_lap: int,
        gtp_lap: int,
        delta_s: float | None,
        clockwise: bool,
    ) -> None:
        self.gtd_phase = gtd_phase
        self.gtp_phase = gtp_phase
        self.gtd_lap = gtd_lap
        self.gtp_lap = gtp_lap
        self.delta_s = delta_s
        self.clockwise = clockwise
        self.update()

    # ------------------------------------------------------------------ #

    def _point(self, phase: float, radius: float, centre: QPointF) -> QPointF:
        """Map a lap phase to a point on the circle, twelve o'clock = phase 0."""
        direction = 1.0 if self.clockwise else -1.0
        angle = -math.pi / 2 + direction * 2 * math.pi * (phase % 1.0)
        return QPointF(
            centre.x() + radius * math.cos(angle),
            centre.y() + radius * math.sin(angle),
        )

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        side = min(self.width(), self.height())
        centre = QPointF(self.width() / 2, self.height() / 2)
        radius = side / 2 - 34

        # --- the lap ---------------------------------------------------
        painter.setPen(QPen(QColor(theme.TEXT), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(centre, radius, radius)

        # --- start/finish line ----------------------------------------
        painter.setPen(QPen(QColor(theme.TEXT), 3))
        painter.drawLine(
            QPointF(centre.x(), centre.y() - radius - 11),
            QPointF(centre.x(), centre.y() - radius + 11),
        )

        # --- direction of travel --------------------------------------
        painter.setPen(QPen(QColor(theme.TEXT_FAINT), 1))
        painter.setFont(QFont(self.font().family(), 9))
        arrow = "\u21bb" if self.clockwise else "\u21ba"
        painter.drawText(
            QRectF(centre.x() + radius - 18, centre.y() - radius - 4, 40, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            arrow,
        )

        # --- cars ------------------------------------------------------
        self._draw_car(painter, self.gtd_phase, radius, centre, theme.GTD, "GTD")
        self._draw_car(painter, self.gtp_phase, radius, centre, theme.GTP, "GTP")

        # --- lap counters ---------------------------------------------
        painter.setPen(QColor(theme.GTD))
        big = QFont(self.font().family(), 1)
        big.setPixelSize(int(side * 0.12))
        big.setWeight(QFont.Bold)
        painter.setFont(big)
        painter.drawText(
            QRectF(centre.x() - radius, centre.y() - radius * 0.62, radius * 2, radius * 0.8),
            Qt.AlignCenter,
            f" GTD Lap {self.gtd_lap}",
        )
        # todo check
        # code added here

        painter.setPen(QColor(theme.GTP))
        small = QFont(self.font().family(), 1)
        small.setPixelSize(int(side * 0.09))
        painter.setFont(small)
        painter.drawText(
            QRectF(centre.x() - radius, centre.y() + radius * 0.16, radius * 2, radius * 0.4),
            Qt.AlignCenter,
            f"GTP Lap {self.gtp_lap}",
        )

        # --- catch delta ----------------------------------------------
        painter.setPen(QColor(theme.TEXT_DIM))
        delta_font = QFont(self.font().family(), 1)
        delta_font.setPixelSize(int(side * 0.055))
        painter.setFont(delta_font)
        if self.delta_s is None:
            text = "no catch"
        else:
            text = f"+{self.delta_s:.0f}s"
        painter.drawText(
            QRectF(centre.x() - radius, centre.y() + radius * 0.52, radius * 2, radius * 0.4),
            Qt.AlignCenter,
            text,
        )
        painter.end()

    def _draw_car(
        self,
        painter: QPainter,
        phase: float,
        radius: float,
        centre: QPointF,
        colour: str,
        label: str,
    ) -> None:
        point = self._point(phase, radius, centre)
        painter.setPen(QPen(QColor(theme.BG), 2))
        painter.setBrush(QColor(colour))
        painter.drawEllipse(point, 9, 9)

        # Label pushed outwards so it never sits on top of the circle.
        outer = self._point(phase, radius + 22, centre)
        painter.setPen(QColor(colour))
        font = QFont(self.font().family(), 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(outer.x() - 22, outer.y() - 9, 44, 18),
            Qt.AlignCenter,
            label,
        )
