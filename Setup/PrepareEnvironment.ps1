python -m pip install --upgrade pip
python -m venv egfet_devices
./egfet_devices/Scripts/Activate.ps1
pip install pip-tools
pip-compile requirements.in
pip-sync requirements.txt
pip install -e .