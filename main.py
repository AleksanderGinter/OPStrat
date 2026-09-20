"""Entry point.

    python -m imsa_strategy.main
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running this file directly from PyCharm as well as with -m.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from imsa_strategy.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("IMSA strategy board")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
