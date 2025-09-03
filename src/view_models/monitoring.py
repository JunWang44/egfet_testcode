import asyncio
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QProgressBar
from pyqtgraph import PlotWidget, mkPen, PlotItem, plot
import pyqtgraph as pg
import numpy as np
from threading import Thread
from multiprocessing import Queue, Event
from typing import List, Tuple, Dict

from core.utils import Config, CellDataRow
from core.event_handling import AbstractDataCallBack
from core.experiment import SequentialState


def sequence(c, z=0):
    while True:
        yield z
        z = z**2 + c


def mandelbrot(candidate):
    return sequence(z=0, c=candidate)


def julia(candidate, parameter):
    return sequence(z=candidate, c=parameter)


def complex_matrix(xmin, xmax, ymin, ymax, pixel_density):
    re = np.linspace(xmin, xmax, int((xmax - xmin) * pixel_density))
    im = np.linspace(ymin, ymax, int((ymax - ymin) * pixel_density))
    return re[np.newaxis, :] + im[:, np.newaxis] * 1j


def is_stable(c, num_iterations):
    z = 0
    for _ in range(num_iterations):
        z = z**2 + c
    return abs(z) <= 2


def get_members(c, num_iterations):
    mask = is_stable(c, num_iterations)
    return c[mask]


def convert_to_si_unit(value):
    si_prefixes = [
        (1e-24, "y"),  # yocto
        (1e-21, "z"),  # zepto
        (1e-21, "z"),  # zepto
        (1e-18, "a"),  # atto
        (1e-15, "f"),  # femto
        (1e-12, "p"),  # pico
        (1e-9, "n"),  # nano
        (1e-6, "µ"),  # micro
        (1e-3, "m"),  # milli
        (1e0, ""),  # base unit
        (1e3, "k"),  # kilo
        (1e6, "M"),  # mega
        (1e9, "G"),  # giga
        (1e12, "T"),  # tera
        (1e15, "P"),  # peta
        (1e18, "E"),  # exa
        (1e21, "Z"),  # zetta
        (1e24, "Y"),  # yotta
    ]

    abs_value = abs(value)
    for factor, prefix in reversed(si_prefixes):
        if abs_value >= factor:
            return value / factor, prefix
    return value, ""  # In case the value is extremely small


class MonitorViewModel(QObject):
    """ViewModel for the monitoring view.

    This class is responsible for updating the monitoring view with the latest
    data from the experiment. It is responsible for updating the plot, the
    current state, and the latest value.
    """

    update_latest_text = Signal(float)
    update_percentage_complete = Signal(int)
    update_plot_signal = Signal(int, float, float)
    update_current_state = Signal(str, int)

    def __init__(self, plot_widget: PlotWidget) -> None:
        super().__init__()
        self.plot_widget = plot_widget
        # Initialize the plot
        c = complex_matrix(-1.5, 0.5, -1, 1, 200)
        members = get_members(c, 200)
        # blue pen

        self.plot_widget.plot(
            members.real,
            members.imag,
            pen=None,
            symbol="o",
            symbolPen="k",
            symbolSize=3,
        )
        # Set the labels
        self.plot_widget.setLabel("left", "Drain Current", units="A")
        self.plot_widget.setLabel("bottom", "Reference Voltage", units="V")
        # Set the title
        self.plot_widget.setTitle("Live Data")
        # Set the background color
        self.plot_widget.setBackground("w")
        # Set the grid
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.show()
        self.data: Dict[int, Tuple[PlotItem, List[float], List[float]]] = dict()
        self.iteration = 0
        self.pens = [
            mkPen(color="k", width=2),
            mkPen(color="r", width=2),
            mkPen(color="g", width=2),
            mkPen(color="b", width=2),
            mkPen(color="c", width=2),
            mkPen(color="m", width=2),
            mkPen(color="y", width=2),
        ]

    def update_current_state_text(
        self, QLabel: QLabel, state: str, cell_index: int
    ) -> None:
        if cell_index >= len(Config.get_instance().cell_names):
            cell_name = "(End)"
        else:
            cell_name = f"({Config.get_instance().cell_names[cell_index]})"
        QLabel.setText(f"State: {state} with cell {cell_name}")

    def update_data(self, index: int, x: float, y: float) -> None:
        gate_voltages, drain_currents = self.data.get(index, ([], []))
        gate_voltages.append(x)
        drain_currents.append(y)
        self.data[index] = (gate_voltages, drain_currents)

        self.plot_widget.clear()
        for index, (x, y) in self.data.items():
            cell_name = Config.get_instance().cell_names[index]
            if len(x) > 100:
                x = x[-500:]
                y = y[-500:]
            pen = self.pens[index % len(self.pens)]
            self.plot_widget.plot(x, y, pen=pen, name=cell_name)
        self.plot_widget.show()

    def update_current_value_text(self, QLabel: QLabel, value: float) -> None:
        value, prefix = convert_to_si_unit(value)
        text = f"Current I<sub>DS</sub>: {value:4.2f} {prefix}A"
        QLabel.setText(text)

    def __call__(self, data: CellDataRow | None) -> None:
        if data is None:
            return

        if (
            data.state == SequentialState.cell_sweep
            #or data.state == SequentialState.stability_sweep
        ):
            ## Set off the plot update signals
            y = data.drain_current
            self.update_latest_text.emit(y)

        if data.state == SequentialState.cell_sweep:
            # calculate remaining percentage
            self.iteration += 1
            start_voltage = Config.get_instance().start_voltage
            end_voltage = Config.get_instance().end_voltage
            step = Config.get_instance().voltage_step
            num_cells = len(Config.get_instance().cell_names)
            num_sweeps = Config.get_instance().num_sweeps
            total_iterations = (
                int((end_voltage - start_voltage) / step) * num_cells * num_sweeps
            )
            self.update_percentage_complete.emit(
                int((self.iteration / total_iterations) * 100)
            )
            if Config.get_instance().reverse:
                x = data.drain_voltage
                y = data.drain_current
            else:
                x = data.gate_voltage
                y = data.drain_current
            self.update_plot_signal.emit(data.cell_index, x, y)

        if data.state == SequentialState.idle:
            self.data.clear()

        if data.state == SequentialState.end:
            self.update_current_state.emit(
                "Configuring for next experiment", data.cell_index + 1
            )
        else:
            self.update_current_state.emit(data.state, data.cell_index)

    def finalize(self) -> None:
        self.data.clear()
        self.iteration = 0
