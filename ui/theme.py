"""Visual tokens for the strategy board.

Design brief: this is read at a glance, from a metre away, by someone who is
also driving a racing car.  So:

* Numbers use tabular figures in a monospaced face -- proportional digits make
  a live clock jitter sideways as the characters change width, which is
  genuinely harder to read at speed.
* Colour carries one meaning only: green is our car, red is the GTP leader,
  amber is a warning.  Nothing decorative uses those three.
* Hierarchy comes from size, not from chrome.  Panels are flat, separated by
  hairlines, because a screen full of rounded cards with drop shadows flattens
  the distinction between the clock and a checkbox.
"""

from __future__ import annotations

BG = "#101418"          # window
PANEL = "#171c22"       # panel fill
PANEL_HI = "#1d242c"    # raised / hovered
LINE = "#2a323c"        # hairline separators
TEXT = "#e6ebf0"
TEXT_DIM = "#8796a5"
TEXT_FAINT = "#5a6672"

GTD = "#35d07f"         # our car
GTP = "#ff4d4d"         # the GTP leader
AMBER = "#ffc44d"       # pit next lap
ACCENT = "#4aa8ff"      # interactive affordances

MONO = "'JetBrains Mono', 'DejaVu Sans Mono', 'Consolas', monospace"
SANS = "'Inter', 'Segoe UI', 'DejaVu Sans', sans-serif"


STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: {SANS};
    font-size: 13px;
}}

QFrame#Panel {{
    background: {PANEL};
    border: 1px solid {LINE};
}}
QFrame#Divider {{
    background: {LINE};
    max-height: 1px;
    border: none;
}}

QLabel#Caption {{
    color: {TEXT_DIM};
    font-size: 11px;
    letter-spacing: 0.4px;
}}
QLabel#Value {{
    color: {TEXT};
    font-family: {MONO};
    font-weight: 600;
}}
QLabel#ValueDim {{
    color: {TEXT_FAINT};
    font-family: {MONO};
    font-weight: 600;
}}

QPushButton {{
    background: {PANEL_HI};
    border: 1px solid {LINE};
    padding: 6px 12px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #232c36; }}
QPushButton:pressed {{ background: #2b3540; }}
QPushButton:checked {{
    background: {ACCENT};
    color: #06121f;
    border-color: {ACCENT};
}}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#Stepper {{
    padding: 0px;
    min-width: 22px;
    max-width: 22px;
    min-height: 20px;
    max-height: 20px;
    font-family: {MONO};
}}
QPushButton#Primary {{
    background: {GTD};
    color: #06180f;
    border: none;
    font-weight: 700;
    padding: 10px 16px;
}}
QPushButton#Primary:hover {{ background: #46e493; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit {{
    background: #0c1015;
    border: 1px solid {LINE};
    padding: 4px 6px;
    color: {TEXT};
    font-family: {MONO};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus {{
    border: 1px solid {ACCENT};
}}

QCheckBox {{ color: {TEXT_DIM}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {LINE};
    background: #0c1015;
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QToolTip {{
    background: {PANEL_HI};
    color: {TEXT};
    border: 1px solid {LINE};
    padding: 4px;
}}
"""
