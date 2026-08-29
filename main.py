# main.py
import logging
import sys

import PySide6.QtWidgets  # noqa: F401  (assure l'initialisation de Qt)
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
