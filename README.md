# PyVISA Data Logger: Keithley 2601B + Bronkhorst EL-FLOW

This repo contains a multithreaded Python data logger for gas-sensing experiments.
It controls a Keithley 2601B source meter and Bronkhorst EL-FLOW mass-flow
controllers via PyVISA, Propar, and PySerial, and streams experiment data to CSV.

The goal is to have a small, configurable “hardware logger” that looks and feels
like production code: clear modules, config-driven, and easy to reuse in analysis
notebooks or ML pipelines.

## Features

- Asynchronous logging from multiple devices (one thread per instrument)
- SCPI / TSP control of Keithley 2601B via `pyvisa` + `keithley2600`
- Bronkhorst EL-FLOW flow control with ppm-based protocol builder
- Autosave to timestamped `data/raw/*.csv` with ISO timestamps
- Configurable NO₂ / H₂S protocols with gas-usage estimation
- Optional JSON export of the exact protocol used, for reproducibility

## Project structure

```text
pyvisa-keithley-bronkhorst-logger/
├─ src/
│  └─ kb_datalogger/
│      ├─ __init__.py
│      ├─ keithley.py        # Keithley2600 wrapper: connect / reset / teardown
│      ├─ protocol.py        # ppm_to_sp, segment_builder, protocol_builder, JSON helpers
│      ├─ mfc.py             # Bronkhorst MFC helpers + MFCThread
│      ├─ threads.py         # Base DeviceThread + KeithleyThread
│      └─ runner.py          # Orchestration: load config, create threads, run session
├─ notebooks/
│  ├─ 01_prototype_V6_drift_control.ipynb   # original lab notebook, cleaned
│  └─ 02_example_analysis.ipynb             # example analysis / plotting of CSV logs
├─ configs/
│  ├─ default_no2_drift.yaml                # main experiment config (flows, speeds, times)
│  └─ lab_pc_example.yaml                   # example with different VISA/COM settings
├─ data/
│  ├─ raw/                                  # CSV output from logger (gitignored, except tiny sample)
│  └─ processed/                            # optional; resampled / cleaned data
├─ examples/
│  └─ example_protocol.json                 # example protocol saved from protocol_builder
├─ tests/
│  ├─ test_ppm_to_sp.py
│  └─ test_protocol_builder.py
├─ README.md
├─ requirements.txt
├─ LICENSE                                  # GPL-3.0
├─ .gitignore
└─ pyproject.toml                           # (optional) install as a package
```

## Getting started

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Install [NI-VISA drivers](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html), since Keithley connection relies on the IVI-VISA driver backend of [pyVISA](https://pyvisa.readthedocs.io/en/latest/introduction/configuring.html). 

3. Verify that PyVISA sees your Keithley 2601B and that the keithley2600 driver can connect:
```python
import pyvisa
from keithley2600 import Keithley2600

INSTR_ADDR = "USB0::0x05E6::0x2601::4120420::INSTR"  # adapt to your setup

# check that Check that PyVISA can talk to the instrument via @ivi backend
# this check can be performed for any instrument
resource_manager = pyvisa.ResourceManager("@ivi")
unknown_instrument = resource_manager.open_resource(INSTR_ADDR)
print(f"Instrument ID: {unknown_instrument.query("*IDN?").strip()}")
inst0.close() 
rm.close()

# now check that keithley can connect with the keithley2600 lib correctly
VISA_LIB_PATH = "C:/Windows/System32/visa64.dll"
k = Keithley2600(INSTR_ADDR, visa_library=VISA_LIB_PATH, raise_keithley_errors=True)
k.connect(); k.disconnect()
```
## Configuration

All experiment settings live in `configs/*.yaml`. The default file
`configs/default_no2_drift.yaml` defines:

- Keithley VISA address, VISA library path, integration time, source voltage

- COM port and node IDs of the Bronkhorst EL-FLOW controllers

- Total and per-MFC maximum flow (sccm)

- Protocol settings: ppm range, ramp speeds, number of repeats, settle times

- Where to store CSV logs and protocol JSON

To adapt to a new setup, copy the default file and edit:

```bash
cp configs/default_no2_drift.yaml configs/my_lab.yaml
# then edit configs/my_lab.yaml
```
and point the runner to it:
```bash
python -m kb_datalogger.runner --config configs/my_lab.yaml
```

(or just change the default path inside `runner.py` if you prefer).

# Running an experiment

1. Power on the Keithley 2601B and Bronkhorst MFCs, make sure COM/VISA addresses
in your YAML file match your hardware.

2. Run:
```bash
python -m kb_datalogger.runner
```

This will:

- connect to Keithley (with a retry + hard reset on failure),

- initialize MFC instruments on the specified `COM` port,

- build a gas protocol from your YAML parameters,

- start a `KeithleyThread` (resistance logging) and one `MFCThread` per node,

- stream data into `data/raw/<timestamp>_resistance.csv` and
`data/raw/<timestamp>_flow_nodeX.csv`.

Optionally, the protocol used is saved as JSON in examples/<timestamp>_protocol.json,
so you can replay or inspect it later.

# Notes for reviewers / hiring managers

The code demonstrates:

multi-device, multithreaded data acquisition,

hardware control via PyVISA / SCPI and Bronkhorst’s Propar API,

clear separation between config, orchestration, and device-level logic,

data logged in analysis-ready CSV for downstream ML/DA workflows.

This project started as a lab notebook and was refactored into a small,
configurable package to show how experimental hardware control can be
structured like production data pipelines.


