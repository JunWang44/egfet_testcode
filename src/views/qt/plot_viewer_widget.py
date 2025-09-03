import matplotlib

matplotlib.use("Qt5Agg")
from PySide6 import QtWidgets, QtCore
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import numpy as np


class MplCanvas(FigureCanvas):

    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super(MplCanvas, self).__init__(fig)


class PlotViewerWidget(FigureCanvas):
    """Widget for displaying a plot."""
    def __init__(self, parent: QtWidgets.QWidget = None):

        self.figure = Figure(figsize=(5, 5))

        # data
        self.x: list[float] = []
        self.y: list[float] = []

        # create an axis
        x = np.linspace(0, 2 * np.pi, 100)
        y = np.sin(x)
        ax = self.figure.add_subplot(111)
        ax.plot(x, y)

        # show canvas
        super().__init__(self.figure)

    def update_plot(self, x: list[float], y: list[float]):
        self.x = x
        self.y = y
        ax = self.figure.add_subplot(111)
        ax.plot(x, y)

    def clear_plot(self):
        self.x = []
        self.y = []
        ax = self.figure.add_subplot(111)
        ax.clear()
        self.figureCanvas.draw()
