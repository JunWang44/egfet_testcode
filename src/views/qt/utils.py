from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QInputDialog

from typing import Optional


def create_message_box(
    message: str, title: str = "Error", parent: Optional[QObject] = None
):
    msgbox = QMessageBox(parent)
    msgbox.setWindowTitle(title)
    msgbox.setText(message)
    msgbox.exec()


def create_input_dialog(
    label: str, title: str = "Input", parent: Optional[QObject] = None
):
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.exec()
    return dialog.textValue()
