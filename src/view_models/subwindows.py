from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QAbstractButton, QPlainTextEdit, QMessageBox
from typing import Callable

from core.utils import Config
from views.qt.utils import create_message_box


class AddCellSubWindowViewModel(QObject):
    """ViewModel for the AddCellSubWindowView."""
    def __init__(self, update_table_signal: Signal):
        super().__init__()
        self.update_table_signal = update_table_signal
        self.cell_name = ""
        self.cell_channel = ""
        self.config = Config.get_instance()

    def update_and_exit(self, window: QObject) -> None:

        if (
            not (cell_name := window.cellNameText.text())
            or not (in_channel := window.channelSelectComboBox.currentText())
            or (
                hasattr(window, "referenceChannelSelectComboBox")
                and not (
                    ref_channel := window.referenceChannelSelectComboBox.currentText()
                )
            )
        ):
            create_message_box("All fields must be filled", parent=window)
            return

        if hasattr(window, "referenceChannelSelectComboBox"):
            if in_channel == ref_channel:
                create_message_box(
                    "input channel cannot be the same as the reference channel",
                    parent=window,
                )
                return
            self.config.reference_channel_mapping[cell_name] = str(ref_channel)

        self.config.cell_channel_mapping[cell_name] = str(in_channel)
        self.config.cell_names.append(cell_name)
        self.update_table_signal.emit()
