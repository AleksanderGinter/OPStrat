"""Main window.

Owns the two timers that drive the whole app:

* **tick timer (100 ms)** -- advances the race model and repaints the things
  that must move smoothly: the clock, the fuel gauge, the dots on the map.
* **refresh latch (5 s or 10 s)** -- repaints the strategy numbers.  Holding
  laps-left and fuel/lap still between refreshes stops them flickering between
  two values on a boundary, which is unreadable at speed.

Exceptions to the latch, by design: the pit warning flash, and anything the
driver has just typed or clicked, which applies immediately.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from ..core.config import DEFAULT_CONFIG_PATH, RaceConfig
from ..core.engine import Engine
from . import theme
from .options_dialog import OptionsDialog
from .panel_left import LeftColumn
from .panel_middle import MiddleColumn
from .panel_right import RightColumn

TICK_MS = 100


class MainWindow(QMainWindow):
    """The strategy board."""

    def __init__(self, engine: Engine | None = None) -> None:
        super().__init__()
        self.setWindowTitle("IMSA strategy board \u2014 GTD")
        self.engine = engine or Engine(RaceConfig.load(DEFAULT_CONFIG_PATH))
        self.time_scale = 1.0       # debug time warp
        self._since_refresh = 0.0

        self._build_ui()
        self._connect()
        self._seed_views()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        self._refresh_all()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.left = LeftColumn()
        self.middle = MiddleColumn()
        self.right = RightColumn()
        self.right.setVisible(False)        # hidden until pinned

        layout.addWidget(self.left, 4)
        layout.addWidget(self.middle, 5)
        layout.addWidget(self.right, 0)
        self.setCentralWidget(central)

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)

        self.setup_action = QAction("Race setup", self)
        self.setup_action.setShortcut(QKeySequence("Ctrl+,"))
        self.setup_action.triggered.connect(self._open_options)
        toolbar.addAction(self.setup_action)

        self.pin_action = QAction("Lap times", self)
        self.pin_action.setCheckable(True)
        self.pin_action.setShortcut(QKeySequence("Ctrl+L"))
        self.pin_action.toggled.connect(self.right.setVisible)
        toolbar.addAction(self.pin_action)

        self.reset_action = QAction("Reset race", self)
        self.reset_action.triggered.connect(self._reset)
        toolbar.addAction(self.reset_action)

        toolbar.addSeparator()
        self.warp_action = QAction("Time \u00d71", self)
        self.warp_action.setToolTip(
            "Debug aid: run the race clock faster to test a whole stint in seconds."
        )
        self.warp_action.triggered.connect(self._cycle_time_scale)
        toolbar.addAction(self.warp_action)

        self.status = QLabel("")
        self.status.setObjectName("Caption")
        self.statusBar().addPermanentWidget(self.status)

        self.setStyleSheet(theme.STYLESHEET)
        self.resize(1320, 820)

    def _connect(self) -> None:
        self.left.start_toggled.connect(self._toggle_clock)
        self.left.mute_toggled.connect(self.engine.toggle_mute)
        self.left.fuel_synced.connect(self._fuel_sync)
        self.left.pit_committed.connect(self._commit_pit)
        self.left.pit_inputs_changed.connect(self._refresh_pit_preview)

        self.middle.gtd_sync.connect(self._gtd_sync)
        self.middle.gtp_sync.connect(self._immediate(self.engine.gtp_sync))
        self.middle.gtp_pitted.connect(self._immediate(self.engine.gtp_pitted))
        self.middle.gtd_lap_stepped.connect(
            lambda d: self._immediate(self.engine.adjust_gtd_lap)(d)
        )
        self.middle.gtp_lap_stepped.connect(
            lambda d: self._immediate(self.engine.adjust_gtp_lap)(d)
        )
        self.middle.gtp_stops_stepped.connect(
            lambda d: self._immediate(self.engine.adjust_gtp_stops)(d)
        )

        self.right.laptime_nudged.connect(
            lambda i, d: self._immediate(self.engine.nudge_laptime)(i, d)
        )
        self.right.gtp_laptime_changed.connect(self._set_gtp_laptime)
        self.right.gtp_pitstop_changed.connect(self._set_gtp_pitstop)

    def _seed_views(self) -> None:
        self.right.seed_from_config(self.engine.config)
        self.left.fuel_sync_input.blockSignals(True)
        self.left.fuel_sync_input.setValue(self.engine.config.tank_size_l)
        self.left.fuel_sync_input.blockSignals(False)

    # ------------------------------------------------------------------ #
    # Command helpers
    # ------------------------------------------------------------------ #

    def _immediate(self, fn):
        """Wrap a command so its effect is visible at once, not at the next latch.

        Anything the driver actively did must not wait up to 10 s to appear.
        """

        def wrapped(*args, **kwargs):
            fn(*args, **kwargs)
            self._refresh_all()

        return wrapped

    def _toggle_clock(self) -> None:
        self.engine.toggle_clock()
        self._refresh_all()

    def _gtd_sync(self) -> None:
        self.engine.gtd_sync()
        self._refresh_all()

    def _fuel_sync(self, litres: float) -> None:
        self.engine.fuel_sync(litres)
        self._refresh_all()

    def _commit_pit(self, litres: float, tyres: bool, repair_s: float) -> None:
        stop = self.engine.commit_pit(litres, tyres, repair_s)
        self.status.setText(
            f"Stop recorded: {stop.fuel_l:.1f} L, {stop.total_time_s:.1f}s lost."
        )
        self._refresh_all()

    def _set_gtp_laptime(self, seconds: float) -> None:
        self.engine.config.gtp_laptime_s = seconds
        self.engine.mark_plan_dirty()
        self._refresh_all()

    def _set_gtp_pitstop(self, seconds: float) -> None:
        self.engine.config.gtp_pitstop_s = seconds
        self.engine.mark_plan_dirty()
        self._refresh_all()

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset race",
            "Clear the clock, laps and fuel and go back to the grid?",
        )
        if answer == QMessageBox.Yes:
            self.engine.reset()
            self._seed_views()
            self._refresh_all()

    def _cycle_time_scale(self) -> None:
        scales = [1.0, 10.0, 60.0]
        self.time_scale = scales[(scales.index(self.time_scale) + 1) % len(scales)]
        self.warp_action.setText(f"Time \u00d7{self.time_scale:.0f}")

    def _open_options(self) -> None:
        dialog = OptionsDialog(self.engine.config, self)
        if dialog.exec() == OptionsDialog.Accepted:
            self.engine.apply_config(dialog.config)
            dialog.config.save(DEFAULT_CONFIG_PATH)
            self.right.seed_from_config(dialog.config)
            self._refresh_all()

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _on_tick(self) -> None:
        dt = (TICK_MS / 1000.0) * self.time_scale
        self.engine.tick(dt)

        derived = self.engine.derived(tyres_planned=self.left.pit_tyres.isChecked())
        self.left.render_fast(derived)
        self.middle.render_fast(derived, self.engine.config.track_clockwise)

        self._since_refresh += TICK_MS / 1000.0
        if self._since_refresh >= self.engine.config.refresh_window_s:
            self._since_refresh = 0.0
            self._render_windowed(derived)

    def _refresh_all(self) -> None:
        """Repaint everything now, bypassing the latch."""
        derived = self.engine.derived(tyres_planned=self.left.pit_tyres.isChecked())
        self.left.render_fast(derived)
        self.middle.render_fast(derived, self.engine.config.track_clockwise)
        self._render_windowed(derived)
        self._since_refresh = 0.0

    def _render_windowed(self, derived) -> None:
        self.left.render_windowed(derived)
        self.middle.render_windowed(derived, self.engine.state.gtp_stops_remaining)
        self.right.render_windowed(derived)

        suggested = self.middle.suggested_next_fuel(derived.plan)
        if suggested is not None:
            self.left.suggest_fuel(suggested)
        self._refresh_pit_preview()

    def _refresh_pit_preview(self) -> None:
        stop = self.engine.preview_pit(
            self.left.pit_fuel.value(),
            self.left.pit_tyres.isChecked(),
            self.left.pit_repair.value(),
        )
        self.left.render_pit_preview(stop)
