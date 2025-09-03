from itertools import combinations
from collections import defaultdict

from core.devices import Multiplexer


class MuxInfoViewModel:
    """ViewModel for the MuxInfoView.
    
    This class is responsible for handling the logic of the MuxInfoView.
    """
    def __init__(self):
        self.mux = Multiplexer.get_instance()

    def get_mux_info(self):
        return self.mux.get_device_info()

    def find_all_connectable_channels(self):
        """Find all connectable channels for the multiplexer device

        Returns:
            dict: A dictionary of connectable channels
        """
        channels = self.mux.get_channels()
        connectable_channels = defaultdict(list)
        with self.mux:
            for channel1, channel2 in combinations(channels, 2):
                if self.mux.can_connect(channel1, channel2):
                    connectable_channels[channel1].append(channel2)
                    connectable_channels[channel2].append(channel1)
        return connectable_channels
