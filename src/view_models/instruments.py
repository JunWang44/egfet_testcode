from dataclasses import dataclass, field
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QAbstractButton, QTableWidget
from PySide6.QtWidgets import QTableWidgetItem
from pathlib import Path
from typing import List, Optional, Callable, Tuple
import pyvisa


from core.utils import Config, bidict
from core.devices import Multiplexer, SourceMeter, AbstractDevice, MockMultiplexer


@dataclass
class CellConnection:
    name: str
    input_channel: str
    reference_channel: Optional[str] = field(default=None)


class InstrumentPanelViewModel(QObject):
    """ViewModel for the InstrumentPanelView.
    
    This class is responsible for handling the logic of the InstrumentPanelView.
    It is responsible for handling the signals and slots of the view.
    """
    # GUI Signals
    devicesChanged = Signal(list)
    vdsSourceChanged = Signal(str)
    vgsSourceChanged = Signal(str)
    topologyChanged = Signal(str)
    tableChanged = Signal()
    # Topology Map
    topology_map = bidict(
        **{
            "external reference": "2524/1-Wire Dual 64x1 Mux",
            "cell reference": "2524/1-Wire Quad 32x1 Mux",
        }
    )

    def __init__(self, mock: bool = False):
        super().__init__()
        self.mock = mock
        self.request_refresh()
        if self.mock:
            self.mux = MockMultiplexer.get_instance("")
        else:
            mux_addr = (
                Config.get_instance().mux_address
                if Config.get_instance().mux_address
                else "PXI1Slot2"
            )
            self.mux = Multiplexer.get_instance(mux_addr)

    @property
    def friendly_topology_name(self) -> str:
        mux_top = self.mux.topology
        friendly_top = self.topology_map.inverse.get(mux_top, [""])[-1]
        return friendly_top.title()

    def get_gpib_devices(self) -> List[str]:
        if self.mock:
            return ["GPIB0::1::INSTR_Mock", "GPIB0::2::INSTR_Mock"]
        resources = pyvisa.ResourceManager().list_resources()
        return [str(r) for r in resources]

    def request_refresh(self) -> None:
        self.devices = self.get_gpib_devices()
        self.devicesChanged.emit(self.devices)

    def set_vds_source(self, vds_source: str) -> None:
        Config.get_instance().vds_address = vds_source
        self.vdsSourceChanged.emit(vds_source)

    def set_vgs_source(self, vgs_source: str) -> None:
        Config.get_instance().vgs_address = vgs_source
        Config.get_instance().vgs_channel = "com0"
        self.vgsSourceChanged.emit(vgs_source)
        self.tableChanged.emit()

    def remove_last_added_cell(self) -> None:
        cell_name = Config.get_instance().cell_names.pop()
        if cell_name in Config.get_instance().cell_channel_mapping:
            Config.get_instance().cell_channel_mapping.pop(cell_name)
        if cell_name in Config.get_instance().reference_channel_mapping:
            Config.get_instance().reference_channel_mapping.pop(cell_name)
        self.tableChanged.emit()

    def get_mux_info(self) -> str:
        with self.mux:
            return self.mux.get_device_info()

    def get_mux_channels(self) -> List[str]:
        with self.mux:
            return self.mux.get_channels()

    def get_channel_connection_display_data(self) -> List[Tuple[str, str]]:
        with self.mux:
            channels = self.mux.get_channels()
        channel_data = []
        for channel in channels:
            if "com" in channel:
                continue
            role = Config.get_instance().channel_mapping.inverse.get(
                channel, ["Undefined"]
            )[-1]
            if role == "Undefined":
                role = Config.get_instance().reference_mapping.inverse.get(
                    channel, ["Undefined"]
                )[-1]
                if role != "Undefined":
                    role = f"{role} Reference"
            channel_data.append((channel, role))

        return channel_data

    @Slot(QAbstractButton)
    def update_topology(self, sender: QAbstractButton):
        mode = sender.text().strip().lower()
        topology = self.topology_map[mode]
        # don't really care if a radio button was reselected
        if self.mux.topology == topology:
            return
        # A change in topology implies something is different
        # best to reset to a new state
        self.mux.topology = topology
        Config.get_instance().mux_address = self.mux._name
        Config.get_instance().mux_topology = topology
        Config.get_instance().cell_names = []
        Config.get_instance().cell_channel_mapping = dict()
        Config.get_instance().reference_channel_mapping = dict()
        self.tableChanged.emit()

    def update_table(self, table: QTableWidget) -> None:
        table.clear()
        table.setHorizontalHeaderLabels(["Channel", "Connection"])
        # Com channels first
        offset = 0
        if "None" not in Config.get_instance().vgs_address:
            table.setItem(
                offset, 0, QTableWidgetItem(Config.get_instance().vgs_channel)
            )
            table.setItem(
                offset, 1, QTableWidgetItem(Config.get_instance().vgs_address)
            )
            offset += 1
        table_data = self.get_channel_connection_display_data()
        with_role, without_role = [], []
        for channel, role in table_data:
            if role != "Undefined":
                with_role.append((channel, role))
            else:
                without_role.append((channel, role))
        with_role = sorted(with_role, key=lambda x: int(x[0][2:]))
        without_role = sorted(without_role, key=lambda x: int(x[0][2:]))
        table_data = with_role + without_role
        for i, (channel, role) in enumerate(table_data):
            table.setItem(i + offset, 0, QTableWidgetItem(channel))
            table.setItem(i + offset, 1, QTableWidgetItem(role))
            if "com" in channel:
                continue

    def handle_reload_from_file(self):
        self.request_refresh()
        self.vdsSourceChanged.emit(Config.get_instance().vds_address)
        self.vgsSourceChanged.emit(Config.get_instance().vgs_address)
        self.tableChanged.emit()
