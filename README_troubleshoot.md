## Troubleshooting

Occasionally, you may get a `niswitch.errors.DriverError: -1074118654: Invalid resource name` error. This is indicative of the host computer not being able to see the PXIe-2025 device through the MXI adapter. In order, the troubleshooting steps you can try are

1. The PC will typically only see the MXI if the device is on and connected when the PC starts up. Restart the PC with the MXI connected.
2. If this does not work, then try reinstalling the NI switch drivers and rebooting.

Sometimes, this may cause the GUI to not start. Check NI-MAX to make sure that the 2524 is connected and visible to the host computer.