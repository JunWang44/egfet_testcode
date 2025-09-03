from collections import defaultdict
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
    QFileDialog,
    QSpinBox,
)
from multiprocessing.synchronize import Event
from multiprocessing import Queue
from typing import Union, Coroutine, Tuple
from pathlib import Path

from core.utils import Config, CellDataRow
from core.devices import Multiplexer, SourceMeter, MockMultiplexer, MockSourceMeter
from core.experiment import (
    ExperimentSupervisor,
    MultiExternalReferenceStrategy,
    SequentialEFGETExperiment,
    ReversedSequentialEGFETExperiment,
    SimpleSamplingStrategy,
    SequentialState,
)

from core.event_handling import DataCallBackThread
from core.utils import CellDataRow
from views.qt.utils import create_message_box, create_input_dialog


class ContentControlsViewModel(QObject):
    """View Model for the content controls.

    This class is responsible for handling the signals from the content controls
    and updating the GUI accordingly.
    """

    # GUI Signals
    trigger_start_experiment = Signal()
    trigger_reload = Signal()

    def __init__(
        self,
        instrument_panel: QWidget,
        experiment_panel: QWidget,
        monitor_panel: QWidget,
        view: QWidget,
    ):
        super().__init__()
        self.view = view
        self.instrument_panel = instrument_panel
        self.experiment_panel = experiment_panel
        self.monitor_panel = monitor_panel

        self.monitor_panel.setDisabled(True)
        self.monitor_pannel_visible = False

        self.instrument_panel_visible = True

    def experiment_toggle(self):
        if self.instrument_panel_visible:
            self.view.experimentSettingsFrame.setDisabled(True)
            self.experiment_panel.setDisabled(False)
            self.instrument_panel.setDisabled(True)
            self.instrument_panel_visible = False
        else:
            self.view.experimentSettingsFrame.setDisabled(False)
            self.instrument_panel.setDisabled(False)
            self.instrument_panel_visible = True
        if self.monitor_pannel_visible:
            self.monitor_panel.setDisabled(True)
            self.monitor_pannel_visible = False
        else:
            self.monitor_panel.setDisabled(False)
            self.monitor_pannel_visible = True

    def save_config(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getSaveFileName(
            self.view,
            "Save Config",
            "",
            "JSON Files (*.json);;All Files (*)",
            options=options,
        )
        if not filename:
            return

        json_string = Config.get_instance().to_json()
        with open(filename, "w") as f:
            f.write(json_string)

    def load_config(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getOpenFileName(
            self.view,
            "Load Config",
            "",
            "JSON Files (*.json);;All Files (*)",
            options=options,
        )
        if not filename:
            return
        with open(filename, "r") as f:
            json_string = f.read()
        config = Config.from_json(json_string)
        Config.set_instance(config)
        self.trigger_reload.emit()

    def set_data_folder(self):
        options = QFileDialog.Options()
        folder = QFileDialog.getExistingDirectory(
            self.view, "Select Data Folder", options=options
        )
        if not folder:
            return
        Path(folder).mkdir(parents=True, exist_ok=True)
        Config.get_instance().data_root = str(folder)

    def set_filename_fix(self):

        # open a dialog to get the prefix and suffix
        prefix = create_input_dialog("Enter the prefix for the filename")
        suffix = create_input_dialog("Enter the suffix for the filename")
        Config.get_instance().prefix = prefix
        Config.get_instance().suffix = suffix

    def set_vds_sweep_mode(self):
        Config.get_instance().reverse = True

    def set_vgs_sweep_mode(self):
        Config.get_instance().reverse = False

    def set_simple_sampling_mode(self):
        Config.get_instance().sampling_mode = "simple"

    def set_stable_mean_sampling_mode(self):
        Config.get_instance().sampling_mode = "stable"

    def set_mean_sampling_mode(self):
        Config.get_instance().sampling_mode = "mean"

    def update_sweep_mode_ui(
        self, sweep_controls_label: QLabel, fixed_source_label: QLabel
    ):
        if Config.get_instance().reverse:
            sweep_controls_label.setText("Drain Voltage Controls")
            fixed_source_label.setText("Gate Voltage Controls")
        else:
            sweep_controls_label.setText("Gate Voltage Controls")
            fixed_source_label.setText("Drain/Source Voltage Controls")


class ExperimentControlsViewModel(QObject):
    """View Model for the experiment controls.

    This class is responsible for handling the signals from the experiment controls.

    """

    waitStateReceived = Signal()

    def __init__(
        self,
        start_trigger: Signal,
        data_collection_shutdown: Event,
        user_event_trigger: Event,
        pause_resume_event: Event,
        data_queue: Queue,
        start_button: QPushButton,
        stop_button: QPushButton,
        pause_resume_button: QPushButton,
        mock: bool = False,
    ):
        super().__init__()
        self.start_trigger = start_trigger
        self.data_collection_shutdown = data_collection_shutdown
        self.user_event_trigger = user_event_trigger
        self.pause_resume_event = pause_resume_event
        self.paused = False
        self.data_queue = data_queue
        self.running = False

        # UI Components
        self.start_button = start_button
        self.stop_button = stop_button
        self.pause_resume_button = pause_resume_button

        self.stop_button.setDisabled(True)
        self.pause_resume_button.setDisabled(True)
        if mock:
            self.mux_class = MockMultiplexer
            self.vds_meter_class = MockSourceMeter
            self.vgs_meter_class = MockSourceMeter
        else:
            self.mux_class = Multiplexer
            self.vds_meter_class = SourceMeter
            self.vgs_meter_class = SourceMeter
        self.async_callbacks = defaultdict(list)

    def add_async_callback(
        self,
        key: SequentialState,
        callback: Union[Coroutine[Tuple[CellDataRow | None, bool], None, None]],
    ):
        self.async_callbacks[key].append(callback)

    def _check_valid_float(self, value: str) -> float | None:
        value = value.strip()
        try:
            return float(value)
        except ValueError:
            return None

    def reload_from_config(
        self,
        drain_text: QLineEdit,
        ids_text: QLineEdit,
        igs_text: QLineEdit,
        start_text: QLineEdit,
        end_text: QLineEdit,
        step_text: QLineEdit,
        experiment_name: QLineEdit,
        sweep_spin: QSpinBox,
        stability_threshold: QLineEdit,
        stability_wait_time: QLineEdit,
    ):
        """Reload the experiment settings from the config.

        Intended to be used with partially parametrized with the correct elements

        Args:
            drain_text: The QLineEdit for the drain voltage
            ids_text: The QLineEdit for the drain current limit
            igs_text: The QLineEdit for the gate current limit
            start_text: The QLineEdit for the start voltage
            end_text: The QLineEdit for the end voltage
            step_text: The QLineEdit for the voltage step
            experiment_name: The QLineEdit for the experiment name
            sweep_spin: The QSpinBox for the number of sweeps
            stability_threshold: The QLineEdit for the stability threshold

        """

        drain_text.setText(str(Config.get_instance().drain_voltage))
        ids_text.setText(str(Config.get_instance().drain_current_limit))
        igs_text.setText(str(Config.get_instance().gate_current_limit))
        start_text.setText(str(Config.get_instance().start_voltage))
        end_text.setText(str(Config.get_instance().end_voltage))
        step_text.setText(str(Config.get_instance().voltage_step))
        experiment_name.setText(Config.get_instance().experiment_name)
        sweep_spin.setValue(Config.get_instance().num_sweeps)
        stability_threshold.setText(
            str(Config.get_instance().stability_threshold * 100)
        )
        stability_wait_time.setText(str(Config.get_instance().stability_wait_time))

    def handle_experiment_ending(self, data: CellDataRow):
        self.start_trigger.emit()

    def handle_user_trigger(self, ready: QPushButton):
        ready.setDisabled(True)
        self.pause_resume_button.setDisabled(False)
        self.user_event_trigger.set()

    def handle_waiting_for_user(self, ready: QPushButton):
        ready.setDisabled(False)
        self.pause_resume_button.setDisabled(True)

    def handle_receive_waiting_state(self, data: CellDataRow):
        self.waitStateReceived.emit()

    def handle_start_signal(self):
        self.running = not self.running
        self.start_button.setDisabled(self.running)
        self.stop_button.setDisabled(not self.running)
        self.pause_resume_button.setDisabled(not self.running)

    def set_experiment_name(self, name_text: QLineEdit, name: str) -> None:
        Config.get_instance().experiment_name = name

    def set_stability_wait_time(self, time_text: QLineEdit, wait_time: str) -> None:
        if (wait_time := self._check_valid_float(wait_time)) == None:
            time_text.setStyleSheet("color: red")
            return
        time_text.setStyleSheet("color: black")
        Config.get_instance().stability_wait_time = wait_time

    def set_stability_threshold(
        self, threshold_text: QLineEdit, threshold: str
    ) -> None:
        # check if the threshold is a valid number
        if (threshold := self._check_valid_float(threshold)) == None:
            # make the text red
            threshold_text.setStyleSheet("color: red")
            return
        # make the text black
        threshold_text.setStyleSheet("color: black")
        Config.get_instance().stability_threshold = threshold / 100

    def set_num_sweeps(self, value: int) -> None:
        Config.get_instance().num_sweeps = value

    def set_drain_voltage(self, drain_text: QLineEdit, voltage: str) -> None:

        # check if the voltage is a valid number
        if (voltage := self._check_valid_float(voltage)) == None:
            # make the text red
            drain_text.setStyleSheet("color: red")
            return
        # make the text black
        drain_text.setStyleSheet("color: black")
        Config.get_instance().drain_voltage = voltage

    def set_gate_start_voltage(self, start_text: QLineEdit, voltage: str) -> None:
        # check if the voltage is a valid number
        if (voltage := self._check_valid_float(voltage)) == None:
            # make the text red
            start_text.setStyleSheet("color: red")
            return
        # make the text black
        start_text.setStyleSheet("color: black")
        Config.get_instance().start_voltage = voltage

    def set_gate_end_voltage(self, gate_end: QLineEdit, voltage: str) -> None:
        # check if the voltage is a valid number
        if (voltage := self._check_valid_float(voltage)) == None:
            # make the text red
            gate_end.setStyleSheet("color: red")
            return
        # make the text black
        gate_end.setStyleSheet("color: black")
        Config.get_instance().end_voltage = voltage

    def set_gate_voltage_step(self, gate_step: QLineEdit, voltage: str) -> None:
        # check if the voltage is a valid number
        if (voltage := self._check_valid_float(voltage)) == None:
            # make the text red
            gate_step.setStyleSheet("color: red")
            return
        # make the text black
        gate_step.setStyleSheet("color: black")
        Config.get_instance().voltage_step = voltage

    def set_ids_current_limit(self, ids_current_limit: QLineEdit, current: str) -> None:
        # check if the current is a valid number
        if (current := self._check_valid_float(current)) == None:
            # make the text red
            ids_current_limit.setStyleSheet("color: red")
            return
        # make the text black
        ids_current_limit.setStyleSheet("color: black")
        Config.get_instance().drain_current_limit = current

    def set_igs_current_limit(self, igs_current_limit: QLineEdit, current: str) -> None:
        # check if the current is a valid number
        if (current := self._check_valid_float(current)) == None:
            # make the text red
            igs_current_limit.setStyleSheet("color: red")
            return
        # make the text black
        igs_current_limit.setStyleSheet("color: black")
        Config.get_instance().gate_current_limit = current

    def start_experiment(self) -> None:
        self.start_trigger.emit()
        self.data_collection_shutdown.clear()
        # Starting the Data Collection Callbacks
        self.data_callback_thread = DataCallBackThread(
            self.data_queue,
            self.data_collection_shutdown,
            self.async_callbacks,
        )
        self.data_callback_thread.start()

        # We can start a separate process to run the experiment here.
        if Config.get_instance().reverse:
            experiment_class = ReversedSequentialEGFETExperiment
        else:
            experiment_class = SequentialEFGETExperiment
        self.supervisor = ExperimentSupervisor(
            experiment=experiment_class,
            vds_meter_class=self.vds_meter_class,
            multiplexer_class=self.mux_class,
            vgs_meter_class=self.vgs_meter_class,
            connection_strategy=MultiExternalReferenceStrategy,
            user_event_trigger=self.user_event_trigger,
            shutdown=self.data_collection_shutdown,
            pause_resume_event=self.pause_resume_event,
            data_queue=self.data_queue,
            config=Config.get_instance(),
            sampling_strategy=SimpleSamplingStrategy,
        )
        self.supervisor.start()
        self.user_event_trigger.set()

    def stop_experiment(self):
        # We can stop the experiment here.
        self.start_trigger.emit()
        self.data_collection_shutdown.set()

    def pause_resume_experiment(self, button: QPushButton):
        # We can pause the experiment here.
        self.pause_resume_event.set()
        self.paused = not self.paused
        if self.paused:
            button.setText("Resume")
        else:
            button.setText("Pause")
