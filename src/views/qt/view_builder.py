from functools import partialmethod, partial
from importlib.resources import files
from multiprocessing import Queue
from multiprocessing import Event
import numpy as np
from PySide6.QtCore import QFile, QIODevice, QObject
from PySide6.QtCore import Signal
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QTableWidgetItem, QDialogButtonBox, QVBoxLayout
import PySide6
import pyqtgraph as pg
from typing import List, Optional, Tuple, Coroutine

from core.event_handling import DataCallBackThread
from core.experiment import SequentialState
from core.io import CSVDataCallBack
from core.utils import CellDataRow, Config
from view_models.instruments import InstrumentPanelViewModel
from view_models.subwindows import AddCellSubWindowViewModel
from view_models.controls import ExperimentControlsViewModel, ContentControlsViewModel
from view_models.monitoring import MonitorViewModel
from views.qt.utils import create_message_box


# region: Add Cell Dialog Builder
class AddCellDialogBuilder:
    """Used as a namespace for building Cell dialog boxes"""

    @staticmethod
    def build(
        update_signal: Signal, parent_vm: InstrumentPanelViewModel
    ) -> Optional[QObject]:
        # load the view from the ui file
        available_channels = parent_vm.get_channel_connection_display_data()
        available_channels = [
            ch for (ch, role) in available_channels if role == "Undefined"
        ]
        temp = parent_vm.get_channel_connection_display_data()
        channels_including_references = []
        for ch, role in temp:
            if role == "Undefined":
                channels_including_references.append(ch)
            if "Reference" in role:
                channels_including_references.append(ch)
        top_name = parent_vm.friendly_topology_name
        match top_name:
            case "Cell Reference":
                add_cell_ui_file = files("views.qt.ui_files").joinpath(
                    "cell_reference_add_cell_dialog.ui"
                )
            case "External Reference":
                add_cell_ui_file = files("views.qt.ui_files").joinpath(
                    "multi_reference_add_cell_dialog.ui"
                )
            case _:
                create_message_box("Reference mode is not selected.")
                return
        add_cell_ui_file = QFile(str(add_cell_ui_file))
        if not add_cell_ui_file.open(QIODevice.ReadOnly):
            raise IOError("Failed to open the Add Cell Dialog UI file")
        loader = QUiLoader()
        view = loader.load(add_cell_ui_file)
        view_model = AddCellSubWindowViewModel(update_signal)
        update_method = partial(view_model.update_and_exit, view)
        view.dialogButtonBox.accepted.connect(update_method)

        if hasattr(view, "referenceChannelSelectComboBox"):
            print(f"Adding references: {channels_including_references}")
            view.referenceChannelSelectComboBox.addItems(channels_including_references)
        view.channelSelectComboBox.addItems(available_channels)
        return view


# endregion:


class MainViewBuilder:
    @staticmethod
    def build(
        mock: bool = False,
    ) -> Tuple[QObject, List[Coroutine[Tuple[CellDataRow | None, bool], None, None]]]:
        """Builds the main view using a Model-View-ViewModel pattern.

        The main view is composed of the following components:
        - Instrument Panel
        - Experiment Panel
        - Monitor Panel

        Each of these components is controlled by a ViewModel class that handles the
        interaction between the view and the underlying model. The main view is also
        responsible for connecting the different components and handling the data flow
        between them.

        Args:
            mock (bool, optional): Whether to use a mock instrument. Defaults to False.

        Returns:
            Tuple[QObject, List[Coroutine[Tuple[CellDataRow | None, bool], None]]]: The main view
                and a list of coroutines for handling data
        """
        # Interprocess Controls
        user_event_trigger = Event()
        data_collection_shutdown = Event()
        pause_resume_event = Event()
        data_queue = Queue()
        error_queue = Queue()
        # load the view from the ui file
        main_ui_file = files("views.qt.ui_files").joinpath("main_view.ui")
        main_ui_file = QFile(str(main_ui_file))
        if not main_ui_file.open(QIODevice.ReadOnly):
            raise IOError("Failed to open the MainWindow UI file")
        loader = QUiLoader()
        view = loader.load(main_ui_file)

        # region: Content Control View Model
        content_vm = ContentControlsViewModel(
            view.instrumentPanel, view.experimentPanel, view.monitorPanel, view
        )
        view.content_vm = content_vm
        content_vm.trigger_start_experiment.connect(content_vm.experiment_toggle)
        view.actionSave_Config.triggered.connect(content_vm.save_config)
        view.actionLoad_Config.triggered.connect(content_vm.load_config)
        view.actionSet_Data_Folder.triggered.connect(content_vm.set_data_folder)
        view.actionFilename_fix.triggered.connect(content_vm.set_filename_fix)

        view.actionSweep_VDS.triggered.connect(content_vm.set_vds_sweep_mode)
        view.actionSweep_VGS.triggered.connect(content_vm.set_vgs_sweep_mode)
        view.actionPt.triggered.connect(content_vm.set_simple_sampling_mode)
        view.actionStableMean.triggered.connect(
            content_vm.set_stable_mean_sampling_mode
        )
        view.actionMean.triggered.connect(content_vm.set_mean_sampling_mode)

        update_sweep_mode = partial(
            content_vm.update_sweep_mode_ui,
            view.sweep_controls_label,
            view.fixed_source_label,
        )
        view.actionSweep_VDS.triggered.connect(update_sweep_mode)
        view.actionSweep_VGS.triggered.connect(update_sweep_mode)
        # endregion: Content Control View Model
        # region: InstrumentPanelViewModel
        # Connect the InstrumentPanel View Model
        instr_vm = InstrumentPanelViewModel(mock)
        view.instr_vm = instr_vm
        # VGS  and VDS Device Selection
        view.refreshDeviceListButton.clicked.connect(view.instr_vm.request_refresh)

        def refresh_items(items: List[str]):
            view.deviceListWidget.clear()
            view.deviceListWidget.addItems(items)

        instr_vm.devicesChanged.connect(refresh_items)
        view.deviceListWidget.addItems(instr_vm.devices)

        def push_selected_vds_source():
            item = view.deviceListWidget.currentItem()
            address = str(item.text())
            instr_vm.set_vds_source(address)

        view.selectVDSDeviceButton.clicked.connect(push_selected_vds_source)

        def update_vds_text(text: str) -> None:
            view.vdsSourceText.setText(f"{text} Selected")

        instr_vm.vdsSourceChanged.connect(update_vds_text)

        def push_selected_vgs_source():
            item = view.deviceListWidget.currentItem()
            address = str(item.text())
            instr_vm.set_vgs_source(address)

        view.selectVGSDeviceButton.clicked.connect(push_selected_vgs_source)

        def update_vgs_text(text: str) -> None:
            view.vgsSourceText.setText(f"{text} Selected")

        instr_vm.vgsSourceChanged.connect(update_vgs_text)

        # Multiplexer Control
        channels = instr_vm.get_mux_channels()
        view.instr_vm = instr_vm
        view.tableWidget.setRowCount(len(channels))
        view.tableWidget.setColumnCount(2)
        view.tableWidget.setHorizontalHeaderLabels(["Channel", "Connection"])
        # Topology Selection
        view.referenceModeButtonGroup.buttonClicked.connect(instr_vm.update_topology)
        # Populate the table
        for i, channel in enumerate(channels):
            view.tableWidget.setItem(i, 0, QTableWidgetItem(channel))
            view.tableWidget.setItem(i, 1, QTableWidgetItem("Undefined"))
        update_table_connection = partial(instr_vm.update_table, view.tableWidget)
        instr_vm.tableChanged.connect(update_table_connection)
        content_vm.trigger_reload.connect(update_table_connection)

        def reload_gpib_device_texts():
            view.vdsSourceText.setText(Config.get_instance().vds_address)
            view.vgsSourceText.setText(Config.get_instance().vgs_address)

        content_vm.trigger_reload.connect(reload_gpib_device_texts)

        def reload_radio_buttons():
            # block signals to prevent the signal from being emitted
            view.referenceModeButtonGroup.blockSignals(True)
            # get friendly topology name
            top_name = instr_vm.friendly_topology_name
            if top_name == "Cell Reference":
                view.cellReferenceRadio.setChecked(True)
            elif top_name == "External Reference":
                view.externalReferenceRadio.setChecked(True)
            view.referenceModeButtonGroup.blockSignals(False)

        content_vm.trigger_reload.connect(reload_radio_buttons)

        # Cell Wiring dialogs
        def connect_dialog_view_model():
            dialog_view = AddCellDialogBuilder.build(instr_vm.tableChanged, instr_vm)
            if dialog_view is None:
                return
            view.dialog = dialog_view
            view.dialog.show()

        view.addCellButton.clicked.connect(connect_dialog_view_model)
        view.removeCellButton.clicked.connect(instr_vm.remove_last_added_cell)
        # endregion:
        #
        # region:Experiment Controls
        exp_vm = ExperimentControlsViewModel(
            content_vm.trigger_start_experiment,
            data_collection_shutdown,
            user_event_trigger,
            pause_resume_event,
            data_queue,
            view.startExperimentButton,
            view.stopExperimentButton,
            view.pauseExperimentButton,
            mock,
        )
        view.exp_vm = exp_vm
        experiment_name_text_control = partial(
            exp_vm.set_experiment_name, view.experimentNameText
        )
        view.experimentNameText.textChanged.connect(experiment_name_text_control)
        drain_text_control = partial(exp_vm.set_drain_voltage, view.drainVoltageText)
        view.drainVoltageText.textChanged.connect(drain_text_control)
        start_text_control = partial(exp_vm.set_gate_start_voltage, view.gateStartText)
        view.gateStartText.textChanged.connect(start_text_control)
        stop_text_control = partial(exp_vm.set_gate_end_voltage, view.gateStopText)
        view.gateStopText.textChanged.connect(stop_text_control)
        step_text_control = partial(exp_vm.set_gate_voltage_step, view.gateStepText)
        view.gateStepText.textChanged.connect(step_text_control)
        stability_text_control = partial(
            exp_vm.set_stability_threshold, view.stabilityThresholdText
        )
        stability_wait_control = partial(
           exp_vm.set_stability_wait_time, view.stabilityWaitTimeInput
        )
        view.stabilityWaitTimeInput.textChanged.connect(stability_wait_control)
        view.stabilityThresholdText.textChanged.connect(stability_text_control)

        view.numSweepsSpin.valueChanged.connect(exp_vm.set_num_sweeps)

        ids_current_limit_text_control = partial(
            exp_vm.set_ids_current_limit, view.idsCurrentLimitText
        )
        view.idsCurrentLimitText.textChanged.connect(ids_current_limit_text_control)
        ig_current_limit_text_control = partial(
            exp_vm.set_igs_current_limit, view.igCurrentLimitText
        )
        view.igCurrentLimitText.textChanged.connect(ig_current_limit_text_control)

        reload_experiment_controls = partial(
            exp_vm.reload_from_config,
            view.drainVoltageText,
            view.idsCurrentLimitText,
            view.igCurrentLimitText,
            view.gateStartText,
            view.gateStopText,
            view.gateStepText,
            view.experimentNameText,
            view.numSweepsSpin,
            view.stabilityThresholdText,
            view.stabilityWaitTimeInput,
        )
        content_vm.trigger_reload.connect(reload_experiment_controls)
        pause_resume_callback = partial(
            exp_vm.pause_resume_experiment, view.pauseExperimentButton
        )
        view.startExperimentButton.clicked.connect(exp_vm.start_experiment)
        view.stopExperimentButton.clicked.connect(exp_vm.stop_experiment)
        view.stopExperimentButton.clicked.connect(exp_vm.user_event_trigger.set)
        view.pauseExperimentButton.clicked.connect(pause_resume_callback)
        user_trigger_control = partial(
            exp_vm.handle_user_trigger, view.readyUserTrigger
        )
        view.readyUserTrigger.clicked.connect(user_trigger_control)
        view.readyUserTrigger.setDisabled(True)
        wait_received_control = partial(
            exp_vm.handle_waiting_for_user, view.readyUserTrigger
        )
        exp_vm.waitStateReceived.connect(wait_received_control)
        exp_vm.start_trigger.connect(exp_vm.handle_start_signal)
        # Plot Viewer
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        plot_widget = pg.PlotWidget(
            view.graphContainer, background="w", title="Live Data"
        )
        plot_layout = QVBoxLayout()
        plot_layout.addWidget(plot_widget)
        view.graphContainer.setLayout(plot_layout)
        plotview_vm = MonitorViewModel(plot_widget)
        view.plotview_vm = plotview_vm
        update_text = partial(
            plotview_vm.update_current_value_text, view.latestValueLabel
        )
        update_state = partial(
            plotview_vm.update_current_state_text, view.experimentStateText
        )
        plotview_vm.update_plot_signal.connect(plotview_vm.update_data)
        plotview_vm.update_latest_text.connect(update_text)
        plotview_vm.update_percentage_complete.connect(view.progressBar.setValue)
        plotview_vm.update_current_state.connect(update_state)
        # Event Handling
        for status in SequentialState:
            exp_vm.add_async_callback(status, plotview_vm)

        exp_vm.add_async_callback(SequentialState.cell_sweep, CSVDataCallBack())
        #exp_vm.add_async_callback(SequentialState.stability_sweep, CSVDataCallBack())
        exp_vm.add_async_callback(SequentialState.end, exp_vm.handle_experiment_ending)
        exp_vm.add_async_callback(
            SequentialState.wait_record, exp_vm.handle_receive_waiting_state
        )
       # exp_vm.add_async_callback(
        #    SequentialState.wait_start, exp_vm.handle_receive_waiting_state
       # )
        return view
