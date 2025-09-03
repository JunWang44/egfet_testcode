from abc import ABCMeta, abstractmethod
from collections import defaultdict
from pathlib import Path
from multiprocessing import Queue
from multiprocessing.synchronize import Event
from threading import Thread
from PySide6.QtCore import QThread, Signal
from typing import Callable, Coroutine, Dict, List, Optional

from core.utils import CellDataRow, Config
from core.experiment import SequentialState

# Constants
DEFAULT_BUFFER_SIZE = 8000  # 8Kb


class AbstractDataCallBack(metaclass=ABCMeta):
    """Abstract base class for data callbacks.

    Data callbacks are used to process data from the experiment. The data
    is passed to the callback as a CellDataRow object. The callback can
    then process the data as needed.

    The finalize method is called when the experiment is complete. This
    allows the callback to perform any cleanup or final processing of the
    data.
    """

    @abstractmethod
    def __call__(self, data: CellDataRow | None) -> None: ...

    @abstractmethod
    def finalize(self) -> None: ...


class ErrorHandlingThread(QThread):
    """Thread for handling errors in the experiment.

    Provides a way for the backend process running the experiment to communicate
    errors to the GUI. The thread will read from a queue and emit a signal when
    an error is received.
    """

    errorSignal = Signal(str, str)

    def __init__(self, queue: Queue, shutdown: Event) -> None:
        super().__init__()
        self.queue = queue
        self.shutdown = shutdown

    def run(self) -> None:
        while not self.shutdown.is_set():
            try:
                error = self.queue.get(timeout=1)
            except:
                continue
            self.errorSignal.emit(error[0], error[1])


class DataCallBackThread(Thread):
    """Contains the event loop for handling data from the experiment.

    Args:
        queue: The queue to read data from
        shutdown: The event to signal the thread to shutdown
        callbacks: The callbacks to run when data is received
    """

    def __init__(
        self,
        queue: Queue,
        shutdown: Event,
        callbacks: Dict[SequentialState, List[AbstractDataCallBack]],
    ) -> None:
        super().__init__()
        self.queue = queue
        self.shutdown = shutdown
        self.callbacks = callbacks

    def update_callbacks(self, callbacks: Dict[str, Callable]) -> None:
        """Update the callbacks to run when data is received
        
        Args:
            callbacks: A dictionary of callbacks to run for each state

        """
        self.callbacks.update(callbacks)

    def run(self) -> None:
        """The event loop for handling data from the experiment.

        The thread will run until the shutdown event is set. It will then
        process any remaining data in the queue and call the finalize method
        on each callback.

        The callbacks are split into groups based on the state of the data
        received. For reference, the states are defined in the Status enum.
        """
        while not self.shutdown.is_set():
            try:
                # get the data from the queue
                data = self.queue.get(timeout=1)
            except:
                continue
            # handle the data
            callbacks = self.callbacks.get(data.state, [])
            for callback in callbacks:
                callback(data)

        # process any remaining data
        while not self.queue.empty():
            data = self.queue.get()
            callbacks = self.callbacks.get(data.state, [])
            for callback in callbacks:
                callback(data)

        for state in SequentialState:
            callbacks = self.callbacks.get(state, [])
            for callback in callbacks:
                if hasattr(callback, "finalize"):
                    callback.finalize()
