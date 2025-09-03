import sys
import logging
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QFile, QIODevice
from typing import Optional, Literal

from core.utils import Config, setup_logger
from views.qt.view_builder import MainViewBuilder


def main(
    config: Optional[Config] = None,
    mock: bool = False,
):
    app = QApplication(sys.argv)
    if config:
        Config.set_instance(config)
    window = MainViewBuilder.build(mock)
    if not window:
        print("Unable to load window")
        sys.exit(-1)
    print("ready")
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    setup_logger()
    main()
