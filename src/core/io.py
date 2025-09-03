from collections import defaultdict
from pathlib import Path
from typing import Dict, Tuple

from core.event_handling import AbstractDataCallBack
from core.utils import Config, CellDataRow
from core.experiment import SequentialState

class CSVDataCallBack(AbstractDataCallBack):
    """ Callback for writing data to CSV files.
    """
    def __init__(self, buffer_size: int = 8000) -> None:
        self.files: Dict[Tuple[int], Path] = dict()
        self.buffers: Dict[Tuple[int, int], str] = dict()
        self.config = Config.get_instance()
        self.buffer_size = buffer_size
        self.stability_sweep_index = 0 

    def __call__(self, data: CellDataRow | None) -> None:
        if data is None:
            return

        if (data.cell_index, data.sweep_index) not in self.files:
            # Make a new file and write the header
            filename = self.filename_from_data(data)
            self.files[(data.cell_index, data.sweep_index)] = filename
            self.buffers[(data.cell_index, data.sweep_index)] = (
                ",".join(data.header) + "\n"
            )
        # Write the data to the buffer
        buffer = ",".join(map(str, CellDataRow.data_as_list(data))) + "\n"
        self.buffers[(data.cell_index, data.sweep_index)] += buffer
        if len(self.buffers[(data.cell_index, data.sweep_index)]) > self.buffer_size:
            # Write the buffer to the file if it is too large
            with open(self.files[(data.cell_index, data.sweep_index)], "a") as f:
                f.write(self.buffers[(data.cell_index, data.sweep_index)])
            self.buffers[(data.cell_index, data.sweep_index)] = ""

    def finalize(self) -> None:
        """Write any remaining data to the files."""
        for (cell_index, sweep_index), buffer in self.buffers.items():
            if buffer:
                with open(self.files[(cell_index, sweep_index)], "a") as f:
                    f.write(buffer)
        self.buffers.clear()

    def filename_from_data(self, data: CellDataRow) -> str:
        """Create a filename from the data."""
        root = self.config.data_path
        cell_name = self.config.cell_names[data.cell_index]
        experiment_name = self.config.experiment_name
        filename = ""
        if self.config.prefix:
            filename += f"{self.config.prefix}_"
        filename += f"{experiment_name}_{cell_name}"
        if self.config.suffix:
            filename += f"_{self.config.suffix}"

        #if data.state == SequentialState.stability_sweep:
         #   filename += f"_stability_sweep_{self.stability_sweep_index}"

        filename += f"_{data.sweep_index}.csv"
        return root / filename
