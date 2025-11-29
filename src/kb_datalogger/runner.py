# src/kb_datalogger/runner.py
"""
High-level orchestration for a single gas-sensing experiment.

Steps:
1. Load configs/config.yaml
2. Connect Keithley 2601B via driver (with retry + hard reset)
3. Initialize Bronkhorst MFC instruments
4. Build gas protocol segments
5. Create timestamp + output file paths
6. Start Keithley + MFC threads
7. Wait for completion or Ctrl-C
8. Clean up instruments
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import time

import yaml

from .keithley import connect_keithley_with_retry, disconnect_keithley
from .mfc import init_mfc_instruments, MFCThread
from .threads import KeithleyThread
from .protocol import protocol_builder, export_protocol_to_json, load_protocol_from_json
from .config import load_config

def run_experiment(config_path: str = "configs/config.yaml") -> None:
    """
    Run a full experiment using the settings from config_path.
    """
    cfg = load_config(config_path)

    exp_cfg = cfg.get("experiment", {})
    k_cfg = cfg["keithley"]
    mfc_cfg = cfg["mfc"]
    prot_cfg = cfg["protocol"]

    # 1) Data dir
    data_dir = Path(exp_cfg.get("data_dir", "data/raw"))
    data_dir.mkdir(parents=True, exist_ok=True)

    # 2) Connect Keithley (with retry + hard reset)
    k, smu = connect_keithley_with_retry(
        address=k_cfg["address"],
        visa_library_path=k_cfg["visa_library_path"],
        integration_time=k_cfg["integration_time"],
        max_retries=2,
        visa_backend=k_cfg.get("visa_backend", "@ivi"),
    )

    # 3) Initialize MFC instruments
    mfc_nodes = list(mfc_cfg["nodes"])
    mfc_vessel = mfc_cfg.get("vessel", "NO2")
    max_flow = float(mfc_cfg["max_flow_sccm"])
    total_flow = float(mfc_cfg["total_flow_sccm"])

    mfc_dict = init_mfc_instruments(
        com_port=mfc_cfg["com_port"],
        nodes=mfc_nodes,
        vessel=mfc_vessel,
        total_flow_rate=total_flow,
        max_flow_rate=max_flow,
    )

    # 4) Build protocol segments
    
    segments = protocol_builder(
        ppm_start=float(prot_cfg["ppm_start"]),
        ppm_end=float(prot_cfg["ppm_end"]),
        speeds=list(prot_cfg["speeds_ppm_per_min"]),
        speed_repeat=int(prot_cfg.get("speed_repeat", 1)),
        protocol_repeat=int(prot_cfg.get("protocol_repeat", 1)),
        total_flow_rate=total_flow,
        max_flow_rate=max_flow,
        vessel=mfc_vessel,
        settle_time=float(prot_cfg.get("settle_time_s", 60.0)),
    )

    # Optional: save protocol alongside data or into examples/
    if exp_cfg.get("save_protocol_json", False):
        protocol_dir = Path(exp_cfg.get("protocol_json_dir", "examples"))
        protocol_json_path = protocol_dir / f"{ts_str}_protocol.json"

        meta = {
            "config_path": config_path,
            "ppm_start": prot_cfg["ppm_start"],
            "ppm_end": prot_cfg["ppm_end"],
            "speeds_ppm_per_min": prot_cfg["speeds_ppm_per_min"],
            "speed_repeat": prot_cfg.get("speed_repeat", 1),
            "protocol_repeat": prot_cfg.get("protocol_repeat", 1),
            "total_flow_sccm": total_flow,
            "max_flow_sccm": max_flow,
            "vessel": mfc_vessel,
        }
        export_protocol_to_json(segments, protocol_json_path, meta=meta)
    
    # segments = load_protocol_from_json("examples/2025-11-29_12-30_protocol.json")
    # protocol_builder is expected to return a list of segments:
    #   [{'duration': seconds, 'ppm_start': x, 'ppm_end': y}, ...]

    # 5) Shared timestamp for all output files
    ts_str = datetime.now().strftime("%H-%M_%d-%m-%y")

    # 6) Create threads
    stop_evt = threading.Event()
    threads: list[threading.Thread] = []

    # 6a) Keithley logging thread (resistance)
    keithley_path = data_dir / f"{ts_str}_resistance.csv"
    keithley_thread = KeithleyThread(
        stop_evt=stop_evt,
        k=k,
        smu=smu,
        source_volt=float(k_cfg["source_voltage"]),
        out_path=keithley_path,
    )
    threads.append(keithley_thread)

    # 6b) MFC threads (one per node)
    for node in mfc_nodes:
        logfile = data_dir / f"{ts_str}_flow_node{node}.csv"
        t = MFCThread(
            node=node,
            inst=mfc_dict[node],
            stop_evt=stop_evt,
            logfile=logfile,
            segments=segments,
            vessel=mfc_vessel,
            total_flow_rate=total_flow,
            max_flow_rate=max_flow,
        )
        threads.append(t)

    # 7) Start threads
    for t in threads:
        t.start()

    # 8) Wait for completion or Ctrl-C
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        print("User pressed Ctrl-C; stopping all threads…")
        stop_evt.set()
        # give threads a chance to exit cleanly
    finally:
        for t in threads:
            t.join()
        # 9) Clean up Keithley
        disconnect_keithley(k, smu)
        print("Experiment finished; instruments disconnected.")


if __name__ == "__main__":
    run_experiment()