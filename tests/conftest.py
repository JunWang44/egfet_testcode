import pytest

from core.utils import Config

@pytest.fixture
def sample_config():
    # Create a sample configuration
    experiment_name = "Sample Experiment"
    vgs_address = "192.168.1.1"
    vds_address = "192.168.1.2"
    start_voltage = 0.0
    end_voltage = 5.0
    voltage_step = 1.0
    min_delay = 0.1
    cells = {
        "Cell1": ["A1", "B1", "C1"],
        "Cell2": ["A2", "B2", "C2"],
        "Cell3": ["A3", "B3", "C3"]
    }

    # Create a Config instance
    config = Config(
        experiment_name=experiment_name,
        vgs_address=vgs_address,
        vds_address=vds_address,
        start_voltage=start_voltage,
        end_voltage=end_voltage,
        voltage_step=voltage_step,
        min_delay=min_delay,
        cells=cells
    )

    return config