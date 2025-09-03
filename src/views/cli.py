import click
import json

# Standard Library Imports
import logging
from multiprocessing import Event, Queue
from pathlib import Path
from typing import Optional


# Custom Imports
from core.utils import setup_logger, Config
from view_models.mux_info import MuxInfoViewModel
from core.experiment import (
    SequentialEFGETExperiment,
    ExperimentSupervisor,
    ExternalReferenceStrategy,
)
from core.devices import SourceMeter, MockSourceMeter, MockMultiplexer, Multiplexer


@click.group()
@click.version_option(package_name="egfet_experiment_controls")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
@click.option(
    "-l",
    "--log",
    type=Path,
    help="Path to the log file",
    default=Path.home() / "egfet_experiment_controls.txt",
)
def cli(verbose, log):
    if verbose:
        level = logging.DEBUG
    else:
        level = logging.ERROR
    setup_logger(log, level)


# launcher commands
@cli.command()
@click.option(
    "-c", "--config", required=False, type=Path, help="Path to the configuration file"
)
@click.option("-m", "--mock", is_flag=True, help="Run the application in mock mode")
def launch_gui(config: Optional[Path] = None, mock: bool = False):
    """Launch the GUI application"""
    from views.gui import main

    if config:
        assert config.exists(), "Config file does not exist"
        config = Config.from_json(config.read_text())
        Config.set_instance(config)
    main(config, mock)


@cli.command()
@click.option(
    "-c", "--config", required=True, type=Path, help="Path to the configuration file"
)
@click.option("-m", "--mock", is_flag=True, help="Run the application in mock mode")
def launch_experiment(config: Optional[Path] = None, mock: bool = False):
    """Launch the experiment application without a GUI"""

    assert config.exists(), "Config file does not exist"
    config_obj = Config.from_json(config.read_text())
    if SequentialEFGETExperiment.verify_config(config_obj):
        Config.set_instance(config_obj)
    else:
        raise ValueError("Invalid configuration file")
    if mock:
        vds_source = MockSourceMeter
        mux = MockMultiplexer
        vgs_source = MockSourceMeter
    else:
        vds_source = SourceMeter
        mux = Multiplexer
        vgs_source = SourceMeter
    supervisor = ExperimentSupervisor(
        experiment=SequentialEFGETExperiment,
        vds_meter_class=vds_source,
        multiplexer_class=mux,
        vgs_meter_class=vgs_source,
        connection_strategy=ExternalReferenceStrategy,
        user_event_trigger=Event(),
        shutdown=Event(),
        pause_resume_event=Event(),
        data_queue=Queue(),
        config=config_obj,
    )
    supervisor.start()

    while not supervisor.shutdown.is_set():
        # get user input
        user_input = input(
            "Enter 'q' to stop the experiment, 'p' to pause, 'r' to resume, 'd' to trigger an event "
        )
        if user_input == "q":
            supervisor.shutdown.set()
            supervisor.user_event_trigger.set()
        elif user_input == "p":
            supervisor.pause_resume_event.set()
        elif user_input == "r":
            supervisor.pause_resume_event.set()
        elif user_input == "d":
            supervisor.user_event_trigger.set()
    supervisor.join()


# Device Based Commands


@cli.command()
def list_devices():
    """List all GPIB devices connected to the computer"""
    import pyvisa

    resources = pyvisa.ResourceManager().list_resources()
    for resource in resources:
        print(resource)


@cli.command()
def multiplexer_info():
    view_model = MuxInfoViewModel()
    click.echo(view_model.get_mux_info())


@cli.command()
@click.option("-s", "--save", required=False, type=Path, help="Save to json file")
def get_channels(save):
    """List all connectable channels for the multiplexer device"""
    click.echo("Multiplexer device selected")
    view_model = MuxInfoViewModel()
    connectable_channels = view_model.find_all_connectable_channels()
    click.echo(connectable_channels)
    if save:
        with save.open("w") as f:
            json.dump(connectable_channels, f)


@cli.command()
@click.option("-n", "--name", required=False, type=str, help="Name of Source Meter")
def sm_info(name):
    """Get the device info of the specified source meter"""
    from core.devices import SourceMeter

    with SourceMeter.get_instance(name) as sm:
        info = sm.get_device_info()
        for k, v in info.items():
            click.echo(f"{k}: {v}")


@cli.command()
@click.option(
    "-v", "--voltage", type=str, required=True, help="A voltage in the range of 0-20V"
)
@click.option("-n", "--name", required=False, type=str, help="Name of Source Meter")
def sm_set_voltage(voltage, name):
    """Set the voltage of the specified source meter"""
    from core.devices import SourceMeter

    with SourceMeter.get_instance(name) as sm:
        sm.set_voltage(voltage)


@cli.command()
@click.option("-n", "--name", required=False, type=str, help="Name of Source Meter")
def sm_measure_read_latency(name):
    """Measure the read latency of the source meter"""

    from core.devices import SourceMeter
    import timeit

    with SourceMeter.get_instance(name) as sm:
        # last measured at 77.4ms/read
        results = timeit.timeit(sm.measure_current, number=1000) / 1000
        print(f"Average execution time: {results:.4e}")

@cli.command()
@click.option("-t", "--topology", type=click.Choice(['0','1','2','3']), help="The channel topology you want to use")
@click.option("-p", "--channel-com-pair", type=str, multiple=True, help="The channel number and com number separated by commas, e.g, '63,4'")
@click.option("-w", "--wait", is_flag=True, help="Set to wait for user input before disconnecting")
def multiplex_test(topology, channel_com_pair, wait):
    topology_map = {
        0:"2524/1-Wire 128x1 Mux",
        1:"2524/1-Wire Dual 64x1 Mux",
        2:"2524/1-Wire Quad 32x1 Mux",
        3:"2524/1-Wire Octal 16x1 Mux"
    }

    topology_name = topology_map[int(topology)]
    channel_pair = []
    for p in channel_com_pair:
        items = p.split(",")
        channel_pair.append((int(items[0]), int(items[1])))

    # parse channel and topology
    with Multiplexer("PXI1Slot2", topology=topology_name) as mux:
        for pair in channel_pair:
            channel, com = pair
            try:
                if mux.can_connect(f"ch{channel}", f"com{com}"):
                    print(f"Can connect channel {channel} and com {com}")
                    mux.connect(f"ch{channel}", f"com{com}")
                else:
                    print(f"Cannot connect channel {channel} and com {com}")
                    break
            except Exception as e:
                print(f"Connection Impossible: {pair}")
                break
        if wait:
            input("Press Enter to reset connections and end program... ")
    


if __name__ == "__main__":
    cli()
