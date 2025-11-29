# src/kb_datalogger/threads.py

import csv
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, Any


PathLike = Union[str, Path]


class DeviceThread(threading.Thread):
    """
    Base class for all device threads.

    Holds a shared stop event so that the runner can signal
    all devices to stop gracefully.
    """

    def __init__(
        self,
        stop_evt: threading.Event,
        name: Optional[str] = None,
    ) -> None:
        super().__init__(daemon=True, name=name)
        self.stop_evt = stop_evt


class KeithleyThread(DeviceThread):
    """
    Thread that periodically measures resistance & voltage from a Keithley SMU
    and logs results to a CSV file.

    Responsibilities:
    - assume the Keithley driver & smu are already configured
    - set source voltage
    - loop until stop_evt is set:
        - read R and V
        - append to CSV: timestamp, V, R
    """

    def __init__(
        self,
        stop_evt: threading.Event,
        k: Any,                  # Keithley2600 instance
        smu: Any,                # k.smua
        source_volt: float,
        out_path: PathLike,
        log_interval_s: float = 0.5,
    ) -> None:
        super().__init__(stop_evt, name="KeithleyThread")
        self.k = k
        self.smu = smu
        self.source_volt = float(source_volt)
        self.out_path = Path(out_path)
        self.log_interval_s = float(log_interval_s)

    def run(self) -> None:
        # Ensure directory exists
        self.out_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"[Keithley] Logging to {self.out_path}")
        # Set source voltage once at start
        try:
            self.k.apply_voltage(self.smu, self.source_volt)
        except Exception as e:
            print(f"[Keithley] Failed to apply voltage {self.source_volt} V: {e}")
            self.stop_evt.set()
            return

        try:
            with self.out_path.open("w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp_iso", "voltage_V", "resistance_Ohm"])

                while not self.stop_evt.is_set():
                    timestamp = datetime.now().isoformat(timespec="milliseconds")
                    try:
                        R = self.smu.measure.r()
                        V = self.smu.measure.v()
                    except Exception as e:
                        print(f"[Keithley] Error measuring: {e}")
                        self.stop_evt.set()
                        break

                    writer.writerow([timestamp, V, R])
                    f.flush()

                    # Throttle logging to avoid hammering the instrument
                    time.sleep(self.log_interval_s)

        except Exception as e:
            print("[Keithley] Thread exiting on unexpected error:", e)
            self.stop_evt.set()

        print("[Keithley] Thread finished.")
