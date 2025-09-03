from core.utils import Config

def test_config_loading(sample_config):
    # assert that the config can be written and read from json
    json_str = sample_config.to_json()
    loaded_config = Config.from_json(json_str)
    assert loaded_config == sample_config