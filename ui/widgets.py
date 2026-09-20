"""Small reusable widgets.

None of these compute anything.  They expose ``set_value``-style methods and
are driven entirely by the ``Derived`` snapshot, which is what keeps the view
layer free of feedback loops.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme


class Panel(QFrame):
    """A flat bordered container."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setFrameShape(QFrame.NoFrame)


class Readout(QFrame):
    """Caption above a large monospaced value."""

    def __init__(
        self,
        caption: str,
        value: str = "--",
        value_px: int = 34,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._value_px = value_px

        self.caption = QLabel(caption)
        self.caption.setObjectName("Caption")

        self.value = QLabel(value)
        self.value.setObjectName("Value")
        self.value.setStyleSheet(f"font-size: {value_px}px;")
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(2)
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_value(self, text: str) -> None:
        if self.value.text() != text:      # avoid needless repaints
            self.value.setText(text)

    def set_colour(self, colour: str) -> None:
        self.value.setStyleSheet(f"font-size: {self._value_px}px; color: {colour};")

    def set_dim(self, dim: bool) -> None:
        self.value.setObjectName("ValueDim" if dim else "Value")
        self.set_colour(theme.TEXT_FAINT if dim else theme.TEXT)


class FlashingReadout(Readout):
    """A readout that can flash amber or red.

    Drives its own 500 ms timer.  ``set_flash(None)`` stops it dead and
    restores the resting colour -- important, because a stuck flash after the
    driver has pitted is worse than no warning at all.
    """

    def __init__(self, caption: str, value_px: int = 34, parent=None) -> None:
        super().__init__(caption, "--", value_px, parent)
        self._colour: str | None = None
        self._on = False
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._blink)

    def set_flash(self, colour: str | None, muted: bool = False) -> None:
        """Set the flash colour, or ``None`` to stop flashing."""
        if colour is None or muted:
            self._timer.stop()
            self._on = False
            # Muted still shows the colour steadily -- only the blink is silenced.
            self.set_colour(colour if (colour and muted) else theme.TEXT)
            self._colour = colour
            return
        if colour != self._colour or not self._timer.isActive():
            self._colour = colour
            self._on = True
            self.set_colour(colour)
            self._timer.start()

    def _blink(self) -> None:
        self._on = not self._on
        self.set_colour(self._colour if self._on else theme.TEXT_FAINT)


class Stepper(QWidget):
    """A label with small + / - buttons beside it."""

    stepped = Signal(int)   # +1 or -1

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = QLabel(text)
        self.label.setObjectName("Value")

        self.minus = QPushButton("\u2212")
        self.minus.setObjectName("Stepper")
        self.plus = QPushButton("+")
        self.plus.setObjectName("Stepper")
        self.minus.clicked.connect(lambda: self.stepped.emit(-1))
        self.plus.clicked.connect(lambda: self.stepped.emit(+1))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.minus)
        layout.addWidget(self.plus)

    def set_text(self, text: str) -> None:
        if self.label.text() != text:
            self.label.setText(text)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


def caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Caption")
    return label
