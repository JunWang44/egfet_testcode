import numpy as np
import logging
from abc import ABCMeta, abstractmethod
from enum import Enum
from statemachine import StateMachine, State
from statemachine.states import States
from threading import Thread
from typing import List, Dict, Optional, Type
from time import time, sleep
from contextlib import ExitStack
from multiprocessing import Process, Queue, Event
from multiprocessing.synchronize import Event as EventType
from pathlib import Path
import soundfile as sf
import sounddevice as sd

# custom imports
from core.devices import AbstractMultiplexer, AbstractSourceMeter
from core.utils import Config, CellDataRow


class AbstractConnectionStrategy:
    """Provides an interface for connection strategies.

    Connection Strategies are used to connect and disconnect cells from the multiplexer.
    In our case, we have the option of two connection strategies: ExternalReferenceStrategy
    and CellReferenceStrategy. The ExternalReferenceStrategy is used when we have an external
    reference electrode that is shared between all cells. The CellReferenceStrategy is used
    when each cell has its own internal reference electrode.

    The purpose in using a connection strategy is to allow for different connection configurations
    to be used with the same experiment. This allows for greater flexibility in the experiment
    setup.
    """

    @abstractmethod
    def connect_cell(self, cell_name: str) -> None: ...

    @abstractmethod
    def disconnect_cell(self, cell_name: str) -> None: ...


class AbstractSamplingStrategy:
    """Provides an interface for sampling strategies.

    Sampling strategies are used to sample data from the source meters. The sampling strategy
    is used to define how the data is sampled. This allows for different sampling strategies
    to be used with the same experiment. This allows for greater flexibility in the experiment
    setup.
    """

    @abstractmethod
    def sample(self) -> np.ndarray: ...


class AbstractExperiment(StateMachine):
    """The ExperimentStateMachine class

    This class is the base class for all experiment state machines. It defines the basic
    structure of an experiment state machine.

    """

    def __init__(
        self,
        vds_meter: AbstractSourceMeter,
        vgs_meter: AbstractSourceMeter,
        multiplexer: AbstractMultiplexer,
        user_event_trigger: EventType,
        emergency_stop: EventType,
        pause_resume_event: EventType,
        data_queue: Queue,
        connection_strategy: AbstractConnectionStrategy,
        sampling_strategy: AbstractSamplingStrategy,
    ):
        self.vds_meter = vds_meter
        self.vgs_meter = vgs_meter
        self.multiplexer = multiplexer
        self.user_event_trigger = user_event_trigger
        self.shutdown = emergency_stop
        self.pause_resume_event = pause_resume_event
        self.data_queue = data_queue
        self.connection_strategy = connection_strategy
        self.sampling_strategy = sampling_strategy
        self.config = Config.get_instance()
        self.logger = logging.getLogger(__name__)
        super().__init__()

    def run(self) -> None:
        raise NotImplementedError

    @staticmethod
    def verify_config(config: Config) -> bool:
        """Verify the configuration

        Args:
            config (Config): The configuration object

        Returns:
            bool: True if the configuration is valid, False otherwise
        """
        raise NotImplementedError

class MultiExternalReferenceStrategy(AbstractConnectionStrategy):
    """Use this strategy when there is an external reference electrode shared between all cells."""

    def __init__(self, mux: AbstractMultiplexer):
        self.mux = mux
        self.vgs_channel = "com0"
        self.reference_common = "com8"
        self.reference_channels = [f"ch{idx}" for idx in range(64, 72)]

    def connect_cell(self, cell_name: str) -> None:
        config = Config.get_instance()
        cell_channel = config.cell_channel_mapping[cell_name]
        reference_channel = config.reference_channel_mapping[cell_name]
        assert reference_channel in self.reference_channels # just check that you're not being dumb
        self.mux.connect(cell_channel, self.vgs_channel)
        self.mux.connect(self.reference_common, reference_channel)

    def disconnect_cell(self, cell_name: str) -> None:
        config = Config.get_instance()
        cell_channel = config.cell_channel_mapping[cell_name]
        reference_channel = config.reference_channel_mapping[cell_name]
        self.mux.disconnect(cell_channel, self.vgs_channel)
        self.mux.disconnect(self.reference_common, reference_channel)


class OnChipStrategy(AbstractConnectionStrategy):
    """Use this strategy when each cell has in internal reference electrode."""

    def __init__(self, mux: AbstractMultiplexer):
        self.mux = mux
        self.vgs_channel = "com0"
        self.reference_common = "com4"

    def connect_cell(self, cell_name: str) -> None:
        config = Config.get_instance()
        cell_channel = config.cell_channel_mapping[cell_name]
        ref_channel = config.reference_channel_mapping[cell_name]
        self.mux.connect(self.vgs_channel, cell_channel)
        self.mux.connect(self.reference_common, ref_channel)

    def disconnect_cell(self, cell_name: str) -> None:
        config = Config.get_instance()
        cell_channel = config.cell_channel_mapping[cell_name]
        ref_channel = config.reference_channel_mapping[cell_name]
        self.mux.disconnect(self.vgs_channel, cell_channel)
        self.mux.disconnect(self.reference_common, ref_channel)


class AveragingSamplingStrategy(AbstractSamplingStrategy):
    def __init__(self, vds_meter:AbstractSourceMeter):
        self.vds_meter = vds_meter

    def sample(self):
        sleep(0.5)
        data = []
        for _ in range(20):
            data.append(self.vds_meter.measure_current())
        return np.mean(data)


class SimpleSamplingStrategy(AbstractSamplingStrategy):
    """Sample the current from the source meter as point measurements."""

    def __init__(self, vds_meter: AbstractSourceMeter):
        self.vds_meter = vds_meter

    def sample(self) -> np.ndarray:
        sleep(0.1)
        return np.mean(self.vds_meter.measure_current())

class StableSamplingStrategy(SimpleSamplingStrategy):
    """Sample the current from the source meter until the current is stable."""

    def __init__(self, vds_meter: AbstractSourceMeter, threshold: float = 0.05):
        super().__init__(vds_meter)
        
        self.threshold = threshold

    def check_relative_threshold(self, data) -> bool:
        diff = np.diff(data)
        max_value = data.max()
        if max_value == 0:
            return False
        return diff.max() / max_value > self.threshold

    def sample(self) -> np.ndarray:
        data = np.empty(10)
        for i in range(10):
            data[i] = super().sample()
        while self.check_relative_threshold(data):
            data = np.roll(data, -1)
            data[-1] = super().sample()
            sleep(1)
        return np.mean(data)


class ExperimentSupervisor(Process):
    def __init__(
        self,
        experiment: Type[AbstractExperiment],
        vds_meter_class: Type[AbstractSourceMeter],
        vgs_meter_class: Type[AbstractSourceMeter],
        multiplexer_class: Type[AbstractMultiplexer],
        connection_strategy: Type[AbstractConnectionStrategy],
        sampling_strategy: Type[AbstractSamplingStrategy],
        user_event_trigger: EventType,
        shutdown: EventType,
        pause_resume_event: EventType,
        data_queue: Queue,
        config: Config,
    ):
        super().__init__()
        Config.set_instance(config)
        self.config = Config.get_instance()
        self.experiment_class = experiment
        self.vds_meter_class = vds_meter_class
        self.vgs_meter_class = vgs_meter_class
        self.multiplexer_class = multiplexer_class
        self.user_event_trigger = user_event_trigger
        self.shutdown = shutdown
        self.pause_resume_event = pause_resume_event
        self.data_queue = data_queue
        self.connection_strategy = connection_strategy
        self.sampling_strategy = sampling_strategy
        self.error_queue = Queue()
        self.logger = logging.getLogger(__name__)

    def run(self):
        """ Run the experiment

        This method is the main entry point for the experiment supervisor. It is responsible
        for creating the experiment and running it. It also handles any exceptions that occur
        during the experiment and logs them.


        """
        Config.set_instance(self.config)
        try:
            # Using ExitStack to ensure that all resources are properly closed even if an exception occurs
            with ExitStack() as stack:
                vds_meter = stack.enter_context(
                    self.vds_meter_class.get_instance(self.config.vds_address)
                )
                vgs_meter = stack.enter_context(
                    self.vgs_meter_class.get_instance(self.config.vgs_address)
                )
                multiplexer = stack.enter_context(
                    self.multiplexer_class.get_instance(self.config.mux_address, topology=self.config.mux_topology)
                )
                match self.config.mux_topology:
                    case "2524/1-Wire Dual 64x1 Mux":
                        connection_strategy = MultiExternalReferenceStrategy(multiplexer)
                    case "2524/1-Wire Quad 32x1 Mux":
                        connection_strategy = OnChipStrategy(multiplexer)
                    case _:
                        raise ValueError(f"Invalid Mux Topology {self.config.mux_topology} or not defined for this experiment type")

                multiplexer.topology = self.config.mux_topology

                match self.config.sampling_mode:
                    case "simple":
                        sampling_strategy = SimpleSamplingStrategy(vds_meter)
                    case "stable":
                        sampling_strategy = StableSamplingStrategy(vds_meter)
                    case "mean":
                        sampling_strategy = AveragingSamplingStrategy(vds_meter)
                    case _:
                        raise Exception("Invalid Sampling Mode")
                # Initialize Experiment
                experiment = self.experiment_class(
                    vds_meter,
                    vgs_meter,
                    multiplexer,
                    self.user_event_trigger,
                    self.shutdown,
                    self.pause_resume_event,
                    self.data_queue,
                    connection_strategy,
                    sampling_strategy,
                )
                self.logger = logging.getLogger(__name__)
                self.logger.info("Starting Experiment")
                while not self.shutdown.is_set():
                    if experiment.current_state.name == "End":
                        break
                    experiment.run()
                #self.logger.info(f"Starting loop {experiment.loop_count + 1} of {self.config.num_loops}")
                self.logger.info("Experiment Complete")
        except Exception as e:
            import traceback as tb

            self.logger.error(f"An error occurred: {e}")
            self.logger.exception(e)
            # get stack trace
            stack_trace = tb.format_exc()
            self.error_queue.put(stack_trace)
        finally:
            self.shutdown.set()


class SequentialState(str, Enum):
    """The Status Enum

    This enum is used to define the status of the experiment.

    """

    idle = "Idle"
   # wait_start = "Waiting for cell to be prepared"
    pause = "Paused"
    resume = "Resumed"
  #  stability_sweep = "Stability Sweep. Please wait"
    wait_record = "Waiting for user to start recording"
    cell_sweep = "Sweeping Cell"
    verify_sweep = "Verify Sweep"
    end = "End"

def play_audio(buffer, sr, event):
    chunk=16000
    idx=60
    sd.play(buffer, blocking=False, samplerate=sr)
    while not event.is_set():
        sleep(1)

    sd.stop()


class SequentialEFGETExperiment(AbstractExperiment):
    """The EGFETExperiment class

    This class is the main experiment class for the EGFET experiment. It is a state machine
    that controls the experiment flow.

    """

    _states: States = States.from_enum(
        SequentialState, initial=SequentialState.idle, final=SequentialState.end
    )

    # State Machine Transitions

    # Pause States
    run = (
        _states.pause.from_(
            _states.cell_sweep, #_states.stability_sweep, 
            cond="pause_resume_triggered"
        )
        | _states.pause.to(_states.resume)
        | _states.resume.to(_states.cell_sweep, cond="prev_state_cell_sweep")
        #| _states.resume.to(_states.stability_sweep, cond="prev_state_stability_sweep")
        | _states.resume.to.itself(internal=True)  # indicates something is wrong
    )

    # Emergency Stop
    run |= _states.end.from_(
        _states.idle,
      #  _states.wait_start,
        _states.wait_record,
        #_states.stability_sweep,
        _states.cell_sweep,
        cond="shutdown_triggered",
    )

    # Normal Flow
    run |= (
        _states.idle.to(_states.wait_record)
       # | _states.wait_start.to(_states.stability_sweep, cond="user_event_triggered")
       # | _states.wait_start.to.itself(internal=True)
       # | _states.stability_sweep.to(_states.wait_record, cond="is_vgs_stable")
       # | _states.stability_sweep.to.itself()
       # | _states.wait_record.to(_states.cell_sweep)
       # | _states.wait_start.to(_states.wait_record, cond="user_event_triggered")
        | _states.wait_record.to(_states.cell_sweep)
        | _states.cell_sweep.to(_states.verify_sweep, cond="is_current_sweep_complete")
        | _states.cell_sweep.to.itself()
        | _states.verify_sweep.to(_states.cell_sweep, cond="sweeps_remaining")
        | _states.verify_sweep.to(_states.end, cond="is_experiment_complete")
        | _states.verify_sweep.to(_states.wait_record)
    )

    def __init__(
        self,
        vds_meter: AbstractSourceMeter,
        vgs_meter: AbstractSourceMeter,
        multiplexer: AbstractMultiplexer,
        user_event_trigger: EventType,
        shutdown: EventType,
        pause_resume_event: EventType,
        data_queue: Queue,
        connection_strategy: AbstractConnectionStrategy,
        sampling_strategy: AbstractSamplingStrategy,
    ):
        super().__init__(
            vds_meter,
            vgs_meter,
            multiplexer,
            user_event_trigger,
            shutdown,
            pause_resume_event,
            data_queue,
            connection_strategy,
            sampling_strategy,
        )

       # self._prev_stability_data: List[np.ndarray] = []
       # self._stability_data: List[np.ndarray] = []

        # State Machine Variables
        self.cell_index = 0
        self.vgs_index = 0
        self.sweep_index = 0
      #  self.loop_count = 0
      #  self.stability_sweep_index = 0
        self.crab_rave = None
        self.crab_rave_shutdown = Event()
        self.crab_rave_buffer, self.crsf = sf.read("C:\\Users\\lmacosta\\Documents\\Python\\EGFET\\egfet-experiment-controls\\src\\assets\\crab_rave.mp3")
        

    # Utility methods

   # def _reset_stability(self):
    #    self._stability_data = []
     #   self._prev_stability_data = []
      #  self.stability_sweep_index = 0

    # Transition Conditions
   # def is_vgs_stable(self):
    #    recorded_complete_sweep = self.vgs_index > int(
     #       (self.config.end_voltage - self.config.start_voltage)
      #      / self.config.voltage_step
       # )

        #if recorded_complete_sweep and self._prev_stability_data and self.stability_sweep_index >= 4:
         #   self._prev_stability_data = self._stability_data
          #  self.vgs_index = 0
           # return True
        #elif recorded_complete_sweep and self.stability_sweep_index < 4: #num_sweeps? so that it is the same as the sweep numbers performed in the experiment
        #    #self._stability_data = []
         #   self.vgs_index = 0
        #    self.stability_sweep_index += 1
        #elif recorded_complete_sweep and self.stability_sweep_index >= 4:
         #   self.vgs_index = 0
          #  self.stability_sweep_index = 0
           # self._prev_stability_data = self._stability_data
           # self._stability_data = []
        #return False

    def is_experiment_complete(self):
        complete = self.cell_index >= len(self.config.cell_names)
        if complete:
            self.cell_index = 0
        return complete
       
    def is_current_sweep_complete(self) -> bool:
        complete = self.vgs_index > int(
            (self.config.end_voltage - self.config.start_voltage)
            / self.config.voltage_step
        )
        if complete:
            self.vgs_index = 0
            self.sweep_index += 1
        return complete

    def sweeps_remaining(self) -> bool:
        sweep_remains = self.sweep_index < self.config.num_sweeps
        if not sweep_remains:
            self.sweep_index = 0
            self.cell_index += 1
        return sweep_remains

    def pause_resume_triggered(self):
        triggered = self.pause_resume_event.is_set()
        self.pause_resume_event.clear()
        return triggered

    def prev_state_cell_sweep(self):
        return self._previous_state == SequentialState.cell_sweep

     #def prev_state_stability_sweep(self):
      #  return self._previous_state == SequentialState.stability_sweep

    def user_event_triggered(self):
        triggered = self.user_event_trigger.is_set()
        self.user_event_trigger.clear()
        return triggered

    def shutdown_triggered(self):
        return self.shutdown.is_set()

    # Transition Actions
    def before_transition(self, event: str, source: State, target: State, event_data):
        if source == self._states.pause:
            return
        self._previous_state = source.value

    def after_transition(self, event: str, source: State, target: State, event_data):
        self.logger.debug(
            f"Running {event} from {source!s} to {target!s}: {event_data.trigger_data.kwargs!r}"
        )

    # State Methods
    def on_enter_pause(self):
        self.logger.debug("Pausing")
        data = CellDataRow(
            0,
            SequentialState.pause,
            self.vgs_index,
            self.cell_index,
            self.sweep_index,
            0,
            0,
            0,
           # loop_count=self.loop_count,
        )
        self.data_queue.put(data)
        self.pause_resume_event.clear()
        self.pause_resume_event.wait()

    def on_exit_resume(self):
        self.logger.debug("Resuming")
        self.pause_resume_event.clear()

    def on_enter_idle(self):
        self.logger.debug("Initializing")

        # Set the VDS and VGS meters to the appropriate settings
        drain_voltage = self.config.drain_voltage
        self.vds_meter.set_voltage(drain_voltage)

        # Current Limits
        drain_current_limit = self.config.drain_current_limit
        gate_current_limit = self.config.gate_current_limit
        self.vds_meter.set_current_limit(drain_current_limit)
        self.vgs_meter.set_current_limit(gate_current_limit)

        # Set binary outputs
        self.vds_meter.configure_output()
        self.vgs_meter.configure_output()
        data = CellDataRow(
            0,
            SequentialState.idle,
            0,
            0,
            0,
            0,
            0,
            0,
           # 0,
        )
        self.data_queue.put(data)

   # def on_enter_wait_start(self):
    #   self.logger.debug("Waiting for User Start")
     #  data = CellDataRow(
      #      0,
      #      SequentialState.wait_start,
       #     self.vgs_index,
        #    self.cell_index,
         #   self.sweep_index,
          #  0,
           # 0,
            #0,
      #  )
       #self.data_queue.put(data)
       #self.crab_rave_shutdown.clear()
       #self.crab_rave = Process(target=play_audio, args=(self.crab_rave_buffer, self.crsf, self.crab_rave_shutdown))
       #self.crab_rave.start()
       #self.user_event_trigger.clear()
       #self.user_event_trigger.wait()
       #self.crab_rave_shutdown.set()

        # Configure Binary outputs
        # set all multiplexer channels to the appropriate cell
        # get cell connection
       #self.vgs_index = 0
       #cell_name = self.config.cell_names[self.cell_index]
       #self.multiplexer.disconnect_all()
       #self.connection_strategy.connect_cell(cell_name)
       #self.start_time = time()

    #def on_enter_stability_sweep(self):
     #   self.logger.debug("Running VGS Stability Sweep")
      #  gate_voltage = (
       #     self.config.start_voltage + self.vgs_index * self.config.voltage_step
        #)
        #self.vgs_meter.set_voltage(gate_voltage) 
        #t = time() - self.start_time
        #drain_current = self.vds_meter.measure_current().squeeze()
        #data = CellDataRow(
        #    t,
        #    SequentialState.stability_sweep,
         #   self.vgs_index,
          #  self.cell_index,
           # self.stability_sweep_index + (5 if self._prev_stability_data else 0),
            #Config.get_instance().drain_voltage,
            #gate_voltage,
            #drain_current,
       # )
        #self.data_queue.put(data)
        #self._stability_data.append(drain_current)
        #self.vgs_index += 1

    def on_enter_wait_record(self):
       self.logger.debug("Waiting for User Start")
       data = CellDataRow(
            0,
            SequentialState.wait_record,
            self.vgs_index,
            self.cell_index,
            self.sweep_index,
            0,
            0,
            0,
            #loop_count=self.loop_count,
        )
       self.data_queue.put(data)
       self.crab_rave_shutdown.clear()
       self.crab_rave = Process(target=play_audio, args=(self.crab_rave_buffer, self.crsf, self.crab_rave_shutdown))
       self.crab_rave.start()
       self.user_event_trigger.clear()
      # self.user_event_trigger.wait()
       self.crab_rave_shutdown.set()

        # Configure Binary outputs
        # set all multiplexer channels to the appropriate cell
        # get cell connection
       self.vgs_index = 0
       cell_name = self.config.cell_names[self.cell_index]
       self.multiplexer.disconnect_all()
       self.connection_strategy.connect_cell(cell_name)
       self.start_time = time()

    def on_exit_wait_record(self):
        self.start_time = time()

    def on_enter_verify_sweep(self):
        self.vgs_index = 0

    def on_enter_cell_sweep(self):
        self.logger.debug("Cell Sweep Iteration")
        gate_voltage = (
            self.config.start_voltage + self.vgs_index * self.config.voltage_step
        )
        self.vgs_meter.set_voltage(gate_voltage)
        self.vgs_index += 1
        t = time() - self.start_time
        # These first two are set by us, so we don't expect any changes
        # we allow for different sampling strategies for drain current since this
        # is mutable and we may want to aggregate measurements
        drain_current = self.sampling_strategy.sample()
        data = CellDataRow(
            t,
            SequentialState.cell_sweep,
            self.vgs_index,
            self.cell_index,
            self.sweep_index,
            Config.get_instance().drain_voltage,
            gate_voltage,
            drain_current,
           # loop_count=self.loop_count,
        )
        self.data_queue.put(data)

    def on_enter_end(self):
        self.logger.debug("Experiment Complete")
        data = CellDataRow(
            0,
            SequentialState.end,
            self.vgs_index,
            self.cell_index,
            self.sweep_index,
            0,
            0,
            0,
          #  loop_count=self.loop_count,
        )
        self.data_queue.put(data)
        self.multiplexer.disconnect_all()
        self.vds_meter.set_voltage(0)
        self.vgs_meter.set_voltage(0)
        self.shutdown.set()
        self.crab_rave_shutdown.set()

    @staticmethod
    def verify_config(config: Config) -> bool:
        return (
            True
            and config.vds_address != "None Selected"
            and config.vgs_address != "None Selected"
            and config.vgs_channel != "None Selected"
            and config.mux_address is not None
            and config.mux_topology is not None
            and config.start_voltage < config.end_voltage
            and config.voltage_step > 0
            and config.drain_current_limit > 0
            and config.gate_current_limit > 0
            and len(config.cell_names) > 0
            and len(config.cell_channel_mapping) > 0
            and len(config.reference_channel_mapping) >= 0
        )

class ReversedSequentialEGFETExperiment(SequentialEFGETExperiment):
    """ For reversed mode, we repurpose any drain configs for the gate voltage.

    This is a subclass of the SequentialEFGETExperiment class. It is used when 
    we want to measure the drain current as a function of drain voltage rather than
    gate voltage. In this case, we repurpose the drain voltage configurations for the
    gate voltage and vice versa.
    """
    def on_enter_idle(self):
        self.logger.debug("Initializing")

        # Set the VDS and VGS meters to the appropriate settings

        drain_voltage = self.config.drain_voltage # hi :)
        self.vgs_meter.set_voltage(drain_voltage)

        # Current Limits
        drain_current_limit = self.config.drain_current_limit
        gate_current_limit = self.config.gate_current_limit
        self.vds_meter.set_current_limit(gate_current_limit)
        self.vgs_meter.set_current_limit(drain_current_limit)

        # Set binary outputs
        self.vds_meter.configure_output()
        self.vgs_meter.configure_output()
        data = CellDataRow(
            0,
            SequentialState.idle,
            0,
            0,
            0,
            0,
            0,
            0,
           # loop_count=self.loop_count,
        )
        self.data_queue.put(data)

    #def on_enter_stability_sweep(self):
     #   self.logger.debug("Running VGS Stability Sweep")
      #  gate_voltage = Config.get_instance().drain_voltage # drain voltage is used to store the constant gate voltage
       # drain_voltage = (
        #    self.config.start_voltage + self.vgs_index * self.config.voltage_step
        #)
        #self.vds_meter.set_voltage(drain_voltage)
        #drain_current = self.vds_meter.measure_current().squeeze()
       # t = time() - self.start_time
        #data = CellDataRow(
         #   t,
          #  SequentialState.stability_sweep,
           # self.vgs_index,
            # self.cell_index,
            #self.sweep_index,
            # in reversed mode drain voltage is repurposed for setting the gate voltage
            #drain_voltage,
            #gate_voltage,
            #drain_current,
        #)
        #self.data_queue.put(data)
        #self._stability_data.append(drain_current)
        #self.vgs_index += 1

    def on_enter_cell_sweep(self):
        self.logger.debug("Cell Sweep Iteration")
        # repurposing vgs index to iterate over drain voltages
        gate_voltage = Config.get_instance().drain_voltage # drain voltage is used to store the constant gate voltage
        drain_voltage = (
            self.config.start_voltage + self.vgs_index * self.config.voltage_step
        )
        self.vds_meter.set_voltage(drain_voltage)
        self.vgs_index += 1
        t = time() - self.start_time
        # These first two are set by us, so we don't expect any changes
        # we allow for different sampling strategies for drain current since this
        # is mutable and we may want to aggregate measurements
        drain_current = self.sampling_strategy.sample()
        data = CellDataRow(
            t,
            SequentialState.cell_sweep,
            self.vgs_index,
            self.cell_index,
            self.sweep_index,
            # in reversed mode drain voltage is repurposed for setting the gate voltage
            drain_voltage,
            gate_voltage,
            drain_current,
           # loop_count=self.loop_count,
        )
        self.data_queue.put(data)


if __name__ == "__main__":
    # get the execution graph
    from core.devices import MockSourceMeter, MockMultiplexer
    from multiprocessing import Queue
    mock_vgs = MockSourceMeter()
    mock_vds = MockSourceMeter()
    mock_mux = MockMultiplexer()
    with ExitStack() as stack:
        vds_meter = stack.enter_context(mock_vds)
        vgs_meter = stack.enter_context(mock_vgs)
        mux = stack.enter_context(mock_mux)
        egfet = SequentialEFGETExperiment(
            mock_vds, mock_vgs, mock_mux, np.linspace(0, 1, 10), 5.0, None, Queue(), None, None
        )
    egfet._graph().write_png("egfet_experiment.png")
