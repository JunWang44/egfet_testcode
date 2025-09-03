import logging
from logging.handlers import RotatingFileHandler
from enum import Enum
from json import JSONEncoder, JSONDecoder
from typing import Dict, List
import json
from sys import stdout
from pathlib import Path
from typing import Optional, Union, Tuple
from collections import UserDict

from dataclasses import dataclass, field


def setup_logger(
    log_file: Path = Path.home() / "egfet-experiment-controls-log.txt",
    log_level: int = logging.ERROR,
):
    """Setup the logger for the application.
    
    Args:
        log_file (Path): The path to the log file.
        log_level (int): The logging level for the logger.
    Returns:
        logging.Logger: The logger object.
    """
    logger = logging.getLogger()
    logger.setLevel(log_level)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = RotatingFileHandler(log_file, maxBytes=1024 * 1024, backupCount=5)
    file_handler.setFormatter(formatter)
    # stream handler
    stream_handler = logging.StreamHandler(stdout)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger


class bidict(dict):
    """A bidirectional dictionary.
    
    This class is a dictionary that allows for bidirectional lookups. It is
    used to store the mapping between the cell names and the multiplexer
    addresses.
    """
    def __init__(self, *args, **kwargs):
        super(bidict, self).__init__(*args, **kwargs)
        self.inverse = {}
        for key, value in self.items():
            self.inverse.setdefault(value, []).append(key)

    def __setitem__(self, key, value):
        if key in self:
            self.inverse[self[key]].remove(key)
        super(bidict, self).__setitem__(key, value)
        self.inverse.setdefault(value, []).append(key)

    def __delitem__(self, key):
        self.inverse.setdefault(self[key], []).remove(key)
        if self[key] in self.inverse and not self.inverse[self[key]]:
            del self.inverse[self[key]]
        super(bidict, self).__delitem__(key)


class JSONCodable(JSONEncoder, JSONDecoder):
    """A class for encoding and decoding JSON data."""
    def to_json(self):
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        return cls(**data)


@dataclass
class Config(JSONCodable):
    """Configuration dataclass

    This class is used to store the configuration of the experiment.
    experiment_name: str
        The name of the experiment
    vgs_address: str
        The address of the Vgs source
    vds_address: str
        The address of the Vds source
    start_voltage: float
        The starting voltage of the experiment
    end_voltage: float
        The ending voltage of the experiment
    voltage_step: float
        The step size of the voltage
    min_delay: float
        The minimum delay between voltage steps. This is calculated empirically
        on the first setup of a experiment.
    cells: Dict[str, List[str]]
        A dictionary of cells. The key is the cell name and the value is a tuple
        of the of the multiplexer addresses for the connections to the transistor
        source, the port to ground, and the the port to the VGS meter.

    """

    data_root: str = field(default=str(Path.home()))
    experiment_name: str = field(default="Experiment")
    vgs_address: str = field(default="None Selected")
    vgs_channel: str = field(default="None Selected")
    vds_address: str = field(default="None Selected")
    drain_voltage: float = field(default=0.0)
    start_voltage: float = field(default=0.0)
    end_voltage: float = field(default=0.0)
    voltage_step: float = field(default=0.0)
    drain_current_limit: float = field(default=0.0)
    gate_current_limit: float = field(default=0.0)
    cell_names: List[str] = field(default_factory=list)
    cell_channel_mapping: Dict[str, str] = field(default_factory=dict)
    reference_channel_mapping: Dict[str, str] = field(default_factory=dict)
    mux_address: Optional[str] = field(default=None)
    mux_topology: Optional[str] = field(default=None)
    stability_threshold: float = field(default=0.01)
    num_sweeps: int = field(default=1)
    prefix: str = field(default="")
    suffix: str = field(default="")
    sampling_mode: str = field(default="simple")
    reverse:bool = field(default=False)
    stability_wait_time:int = field(default=0)
    #num_loops:int = field(default=4) # here is where you define the amount of loops 

    @property
    def channel_mapping(self) -> bidict:
        return bidict(**self.cell_channel_mapping)

    @property
    def reference_mapping(self) -> bidict:
        return bidict(**self.reference_channel_mapping)

    @property
    def data_path(self) -> Path:
        return Path(self.data_root)

    @classmethod
    def get_instance(cls) -> "Config":
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance

    @classmethod
    def set_instance(cls, config: "Config") -> None:
        if not hasattr(cls, "_instance"):
            cls._instance = config
        else:
            cls._instance.__dict__.update(config.__dict__)


@dataclass
class CellDataRow:
    time: float
    state: str
    vgs_index: int
    cell_index: int
    sweep_index: int
    drain_voltage: float
    gate_voltage: float
    drain_current: float
  #  loop_count: int 

    @property
    def header(self) -> List[str]:
        return [
            "Time",
            "Drain Voltage",
            "Gate Voltage",
            "Drain Current",
        ]

    @staticmethod
    def data_as_list(data: "CellDataRow") -> List:
        return [
            data.time,
            data.drain_voltage,
            data.gate_voltage,
            data.drain_current,
        ]
