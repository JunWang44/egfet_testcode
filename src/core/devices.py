import niswitch
import pyvisa
import contextlib
from functools import lru_cache
from abc import ABCMeta, abstractmethod
import logging
from typing import Optional, Dict
from enum import Enum
import numpy as np
from time import sleep

from core.utils import bidict, Config


class RequestError(Exception):
    pass


# region [Abstract Classes]


class AbstractDevice(metaclass=ABCMeta):
    """Abstract Base Class for Devices

    This class is an abstract base class for all devices. It provides a
    common interface for all devices to implement. This class also provides
    a class method to get an instance of the device. This class is a singleton
    class and will only create one instance of the device. If the device is
    already created, then the instance will be returned.
    """

    # Class Variables
    _instances: Dict[str, "AbstractDevice"] = dict()

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def get_device_info(self) -> dict: ...

    @abstractmethod
    def __enter__(self) -> "AbstractDevice": ...

    @abstractmethod
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...

    @classmethod
    def get_instance(cls, name: Optional[str] = None, mock: bool = False, **kwargs):
        """Get an instance of the device
        
        This method implements a factory pattern to get an instance of the device.
        If the device is already created, then the instance will be returned. If the
        device is not created, then a new instance will be created. We treat every instance with a
        unique name as a separate instance. If the name is not provided, then the default
        instance will be returned. The default instance is stored as 'default' in the class 
        variable.

        We also provide an option to mock the device. If the mock flag is set to True, then
        a mock instance of the device will be returned. This is useful for testing the application
        without the actual hardware.

        Args:
            name (Optional[str], optional): The name of the device. Defaults to None.
            mock (bool, optional): If the device should be mocked. Defaults to False.
        
        Returns:
            AbstractDevice: An instance of the device
        """
        if name is not None:
            # get the instance by name
            instance = cls._instances.get(name, None)
        else:
            # get the default instance
            instance = cls._instances.get("default", None, )
        if instance is not None:
            return instance
        instance = cls(name, simulate=mock, **kwargs)
        # store the instance as a class variable
        cls._instances[name or "default"] = instance
        return instance


class AbstractSourceMeter(AbstractDevice):
    """Provides an common interface for Source Meters"""

    @abstractmethod
    def measure_current(self) -> np.ndarray: ...

    @abstractmethod
    def measure_voltage(self) -> np.ndarray: ...

    @abstractmethod
    def set_voltage(self, voltage: float) -> None: ...

    @abstractmethod
    def set_current_limit(self, limit: float) -> None: ...

    @abstractmethod
    def configure_output(self) -> None: ...


class AbstractMultiplexer(AbstractDevice):
    """Provides an common interface for Multiplexers"""

    @abstractmethod
    def get_channels(self) -> list: ...

    @abstractmethod
    def can_connect(self, channel1: str, channel2: str) -> bool: ...

    @abstractmethod
    def connect(self, channel1: str, channel2: str) -> None: ...

    @abstractmethod
    def disconnect(self, channel1: str, channel2: str) -> None: ...

    @abstractmethod
    def disconnect_all(self) -> None: ...


# endregion [Abstract Classes]

# region [Devices]
    

class Multiplexer(AbstractMultiplexer):
    """Multiplexer Device
        This class is a wrapper around the niswitch library to interact with
        the multiplexer. By default, this class will connect to 'PXI1Slot2'
        which is the default address for the multiplexer.
        """
    valid_topologies = [
        "2524/1-Wire 128x1 Mux",
        "2524/1-Wire Dual 64x1 Mux",
        "2524/1-Wire Quad 32x1 Mux",
        "2524/1-Wire Octal 16x1 Mux",
        "2524/1-Wire Sixteen 8x1 Mux",
    ]

    def __init__(
        self, name: str, topology: Optional[str] = None, simulate: bool = False
    ):
        super().__init__()
        self._name = name
        if topology is None:
            topology = self.valid_topologies[0]
        self.topology = topology
        self.simulate = simulate

    @property
    def topology(self) -> str:
        return self._topology

    @topology.setter
    def topology(self, top: str) -> None:
        """Set the topology of the multiplexer
        
        We want to make sure that the topology is a valid topology. If the
        topology is not valid, then we raise a ValueError.

        Args:
            top (str): The topology of the multiplexer

        Raises:
            ValueError: If the topology is not valid
        """
        if top not in self.valid_topologies:
            raise ValueError(f"Invalid Multiplexer Topology: {top}")
        self._topology = top
        self._reset_device = True

    def get_channels(self) -> list:
        """Get the channels for the multiplexer device

        Returns:
            list: A list of channels
        """
        try:
            channel_count = self._session.channel_count
            channels = []
            for i in range(1, channel_count + 1):
                channel_name = self._session.get_channel_name(i)
                channels.append(str(channel_name))
            return channels
        except Exception as e:
            self.logger.error("Error received from the multiplexer device")
            self.logger.exception(e)
            return []

    def can_connect(self, channel1: str, channel2: str) -> bool:
        """Check if two channels can be connected

        Args:
            channel1 (str): The first channel
            channel2 (str): The second channel

        Returns:
            bool: True if the channels can be connected, False otherwise
        """
        try:
            connectable = self._session.can_connect(channel1, channel2)
        except Exception as e:
            self.logger.error("Error received from the multiplexer device")
            self.logger.exception(e)
        return connectable

    def disconnect_all(self) -> None:
        """Disconnect all channels"""
        try:
            self._session.disconnect_all()
        except Exception as e:
            self.logger.error("Unable to disconnect")
            self.logger.exception(e)

    def disconnect(self, channel1: str, channel2: str) -> None:
        """Disconnect two channels
        
        Args:
            channel1 (str): The first channel
            channel2 (str): The second channel

        """
        try:
            self._session.disconnect(channel1, channel2)
        except Exception as e:
            self.logger.error(f"Error disconnecting {channel1} and {channel2}")
            self.logger.exception(e)
            raise RequestError(f"Unable to disconnect {channel1} and {channel2}")

    def connect(self, channel1: str, channel2: str) -> None:
        """Connect two channels

        Args:
            channel1 (str): The first channel
            channel2 (str): The second channel

        Raises:
            RequestError: If there is an error connecting the channels
        """
        try:
            self._session.connect(channel1, channel2)
        except Exception as e:
            self.logger.error(f"Error connecting {channel1} and {channel2}")
            self.logger.exception(e)
            raise RequestError(f"Error connecting {channel1} and {channel2}")

    def get_device_info(self) -> dict:
        return {"name": self._name}

    ## Context Handling Methods
    def __enter__(self):
        """Open a session with the multiplexer device"""

        try:
            if self.simulate:
                self.logger.debug(f"Simulating with topology {self.topology}")
            else:
                self.logger.debug(f"Opening {self._name} with topology {self.topology}")
            self._session = niswitch.Session(
                self._name,
                self.topology,
                reset_device=self._reset_device,
                simulate=self.simulate,
            )
            self._reset_device = False
        except Exception as e:
            self.logger.error(f"Error opening session with {self._name}")
            self.logger.exception(e)
            raise e
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Close the session with the multiplexer device"""
        self.logger.debug(f"Closing multiplexer session")
        self._session.close()
        self._session = None
        return False


class SourceMeter(AbstractSourceMeter):
    """Source Meter Device
        This class is a wrapper around the pyvisa library to interact with
        the source meters. By default, this class will connect to 'GPIB0::26::INSTR'
        which is the default address for the source meter. 
        """
    class StateEnum(str, Enum):
        init = "Initializing"
        readVoltage = "Voltage Reading Mode"
        readCurrent = "Current Reading Mode"
        setVoltage = "Voltage Writing Mode"
        setCurrentLimit = "Current Limit Setting Mode"

    def __init__(
        self,
        name: Optional[str] = None,
        current_level: str = "10e-3",
        voltage_range: str = "20",
        voltage_set: str = "5",
        *args,
        **kwargs,
    ):
        
        super().__init__()
        self._name = name or "GPIB0::26::INSTR"
        self._resource: Optional[pyvisa.resources.Resource] = None
        self._prev_state = SourceMeter.StateEnum.init
        self._current_levels = current_level
        self._voltage_range = voltage_range
        self._voltage_level = voltage_set

    def measure_current(self) -> np.ndarray:
        """Measure the current from the source meter

        If the previous state is not set to read current, then the source meter
        will be set to read current mode before reading the current.

        Returns:
            np.ndarray: An array of current values
        """
        if self._prev_state != SourceMeter.StateEnum.readCurrent:
            # set to read current mode then read the current
            self._resource.write(':sens:func "CURR"')
            self._resource.write(f":sens:curr:prot {self._current_levels}")
            self._resource.write(f":sens:curr:rang {self._current_levels}")
            self._resource.write(":outp on")
            self._prev_state = SourceMeter.StateEnum.readCurrent
        # reads a single point
        data = self._resource.query_binary_values(
            ":meas:curr?", datatype="f", container=np.ndarray, is_big_endian=True
        )
        return data

    def measure_voltage(self):
        """ Measure the voltage from the source meter

        It does this as a single measurement. If the previous state is not set to read voltage,
        then the source meter will be set to read voltage mode before reading the voltage.
        This makes sure that we set the correct configuration before reading the voltage.

        Returns:
            np.ndarray: An array of voltage values
        """
        if self._prev_state != SourceMeter.StateEnum.readVoltage:
            self._resource.write(":sens:func volt")
        data = self._resource.query_binary_values(
            ":read:arr:volt?", datatype="f", container=np.ndarray, is_big_endian=True
        )
        return data

    def set_voltage(self, voltage: float):
        if self._prev_state != SourceMeter.StateEnum.setVoltage:
            self._resource.write(":sour:func volt")
            self._resource.write(":sour:volt:mode fix")
            self._resource.write(f":sour:volt:range {self._voltage_range}")
            self._resource.write(":outp on")
        if voltage == None:
            voltage = self._voltage_level
        self._resource.write(f":sour:volt:lev {voltage}")

    def set_current_limit(self, limit: float):
        """Set the current limit of the source meter

        Assumes that the current limit is in milliamps

        Args:
            limit (float): The current limit in milliamps

        """
        if self._prev_state != SourceMeter.StateEnum.setCurrentLimit:
            self._resource.write(':sens:func "CURR"')
        limit = int(limit)
        self._resource.write(f":sens:curr:prot {limit}e-3")
        # # Current range is set to the nearest power of 10
        # if limit < 10:
        #     self._resource.write(f":sens:curr:rang 10e-3")
        # elif limit < 100:
        #     self._resource.write(f":sens:curr:rang 100e-3")

    def configure_output(self):
        """Configure the output of the source meter

        By default, we should be running in binary mode. This means that the
        output is returned as a binary string in 32-bit IEEE 754 format. By default, we
        use numpy arrays as the container for the data.

        """
        self._resource.write(":form real,32")

    def get_device_info(self) -> dict:
        """Get the device information

        Returns:
            dict: A dictionary of the device information
        """
        return {"name": self._name, "device": self._resource.query("*IDN?")}

    def __enter__(self):
        rm = pyvisa.ResourceManager()
        self.logger.debug(f"Opening {self._name}")
        try:
            self._resource = rm.open_resource(self._name)
            # clear out device
            self._resource.write("*rst; status:preset; *cls")
            self._resource.write(":outp off")
        except Exception as e:
            self.logger.exception(e)
            self.logger.error(f"Failed to open {self._name}")
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._resource = None
        return super().__exit__(exc_type, exc_value, traceback)


# endregion [Devices]
# region Mock Devices


class MockMultiplexer(Multiplexer):

    def __init__(self, name="PXI1Slot2", *args, **kwargs):
        super().__init__(name)
        self.logger.info(f"Using Mock Multiplexer")
        self._channels = [
            "CH1",
            "CH2",
            "CH3",
            "CH4",
            "CH5",
            "CH6",
            "CH7",
            "CH8",
            "CH9",
            "CH10",
            "com0",
            "com8",
        ]
        self._context_counter = 0

        # mock channel connections
        y1 = np.sin
        y2 = np.cos
        y4 = np.tan
        y3 = np.tanh
        y5 = np.arctan
        y6 = np.arctanh

        self._data = {"CH1": y1, "CH2": y2, "CH3": y3, "CH4": y4, "CH5": y5, "CH6": y6}
        self._connections: bidict[str, str] = bidict()

    def get_channels(self) -> list:
        """Get the channels for the multiplexer device

        Returns:
            list: A list of channels
        """
        if self._context_counter == 0:
            raise RequestError("No active context")
        return self._channels

    def can_connect(self, channel1, channel2) -> bool:
        """Check if two channels can be connected

        Args:
            channel1 (str): The first channel
            channel2 (str): The second channel

        Returns:
            bool: True if the channels can be connected, False otherwise
        """
        if self._context_counter == 0:
            raise RequestError("No active context")
        return channel1 in self._channels and channel2 in self._channels

    def connect(self, channel1, channel2) -> None:
        """Connect two channels

        Args:
            channel1 (str): The first channel
            channel2 (str): The second channel

        Raises:
            RequestError: If there is an error connecting the channels
        """
        if self._context_counter == 0:
            raise RequestError("No active context")

        if channel1 in self._channels and channel2 in self._channels:
            if (
                channel1 in self._connections
                or channel1 in self._connections.inverse
                or channel2 in self._connections
                or channel2 in self._connections.inverse
            ):
                raise RequestError(f"Channel already connected")
            self._connections[channel2] = channel1
        else:
            raise RequestError(f"Invalid channels {channel1} and {channel2}")

    def disconnect(self, channel1, channel2) -> None:
        if self._context_counter == 0:
            raise RequestError("No active context")
        if channel1 in self._connections:
            del self._connections[channel1]
        if channel2 in self._connections:
            del self._connections[channel2]
        else:
            raise RequestError(f"Channel {channel1} not connected")

    def get_device_info(self) -> dict:
        if self._context_counter == 0:
            raise RequestError("No active context")
        return {"name": self._name}

    def disconnect_all(self) -> None:
        if self._context_counter == 0:
            raise RequestError("No active context")
        self._connections.clear()

    ## Context Handling Methods
    def __enter__(self):
        self.logger.info(f"Opening session with {self._name}")
        self._context_counter += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.logger.info(f"Closing session with {self._name}")
        self._context_counter -= 1
        return False


class MockSourceMeter(AbstractSourceMeter):
    def __init__(
        self,
        name: Optional[str] = None,
        current_level: str = "10e-3",
        voltage_range: str = "20",
        voltage_set: str = "5",
        *args,
        **kwargs,
    ):
        super().__init__()
        self._name = name or "Mock Source Meter"
        self.logger.info(f"Using Mock Source Meter")
        self._prev_state = SourceMeter.StateEnum.init

        self.t_idx = 0
        self._context_counter = 0
        config = Config.get_instance()
        self.vgs_channel = config.vgs_channel
        self._voltage = 0
        self.mux = MockMultiplexer.get_instance(config.mux_address)

    def measure_current(self) -> np.ndarray:
        """Measure the current from the source meter

        If the previous state is not set to read current, then the source meter
        will be set to read current mode before reading the current.

        Returns:
            np.ndarray: An array of current values
        """
        if self._context_counter == 0:
            raise RequestError("No active context")
        if self._prev_state != SourceMeter.StateEnum.readCurrent:
            # set to read current mode then read the current
            self._prev_state = SourceMeter.StateEnum.readCurrent
        sleep(0.077)  # last measured at 77.4ms/read

        connection = self.mux._connections.get(self.vgs_channel, "Nope")
        func = self.mux._data.get(connection, np.ones(100) * -9.69)
        try:
            if self._name == Config.get_instance().vds_address:
                v = MockSourceMeter.get_instance(
                    Config.get_instance().vgs_address
                )._voltage
                data = func(v) + np.random.randn() * 0.5
            else:
                data = func(self._voltage)
        except Exception as e:
            self.logger.error(f"Error reading current from {self.vgs_channel}")
            self.logger.exception(e)
            data = np.zeros(1)
        return data

    def measure_voltage(self):
        return self._voltage

    def set_voltage(self, alt_voltage: float = None):
        if self._context_counter == 0:
            raise RequestError("No active context")
        if self._prev_state != SourceMeter.StateEnum.readVoltage:
            self._prev_state = SourceMeter.StateEnum.setVoltage
        self._voltage = alt_voltage
        sleep(0.05)

    def set_current_limit(self, limit: float):
        if self._context_counter == 0:
            raise RequestError("No active context")
        if self._prev_state != SourceMeter.StateEnum.setCurrentLimit:
            self._prev_state = SourceMeter.StateEnum.setCurrentLimit
        sleep(0.05)

    def configure_output(self):
        if self._context_counter == 0:
            raise RequestError("No active context")
        sleep(0.05)

    def get_device_info(self) -> dict:
        """Get the device information

        Returns:
            dict: A dictionary of the device information
        """
        return {"name": self._name, "device": "Mock Source Meter"}

    def __enter__(self):
        self.logger.info(f"Opening {self._name}")
        self._context_counter += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._context_counter -= 1
        return super().__exit__(exc_type, exc_value, traceback)


# endregion Mock Devices
