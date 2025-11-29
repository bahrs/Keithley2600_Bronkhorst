# src/kb_datalogger/config.py
import yaml
from typing import Dict, Any

def load_config(config_path: str = "configs/config.yaml") -> Dict[str, Any]:
    """
    Load YAML config for the experiment.

    Expected structure (example):

    experiment:
      data_dir: "data/raw"

    keithley:
      address: "USB0::0x05E6::0x2601::4120420::INSTR"
      visa_library_path: "C:/Windows/System32/visa64.dll"
      visa_backend: "@ivi"
      integration_time: 0.01
      source_voltage: 10.0

    mfc:
      com_port: "COM12"
      nodes: [7, 8, 9, 11]
      max_flow_sccm: 50.0
      total_flow_sccm: 100.0
      vessel: "NO2"

    protocol:
      ppm_start: 0.0
      ppm_end: 20.0
      speeds_ppm_per_min: [1.0]
      speed_repeat: 1
      protocol_repeat: 1
      settle_time_s: 60.0
    """
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


'''# Keithley
KEITHLEY_ADDR = "USB0::0x05E6::0x2601::4120420::INSTR"
SOURCE_VOLT   = 10.0  # volts
KEITHLEY_INTEG_TIME = 0.01  # 0.001 is the smallest in-keithley delay. Increase to 0.03 for ~10Hz

# MFC
COM_PORT      = "COM12"
MFC_NODES     = [7, 8, 9, 11]   # order: 7 → 8 → 9 → 11
MAX_FLOW      = 50.0      # max flow through one MFC in sccm (cm3/min)
TOTAL_FLOW    = 100.0     # total flow in sccm
VESSEL        = "NO2"

# Paths
DEFAULT_DATA_DIR = "data/raw"'''
