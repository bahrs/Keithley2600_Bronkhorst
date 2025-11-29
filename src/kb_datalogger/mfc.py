import csv
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Union, Optional

import propar

from .threads import DeviceThread
from .protocol import ppm_to_sp

PathLike = Union[str, Path]

"""TODO:
- think about setting the setpoints upon initialization so the sensor readings 
settle before the start of the protocol 
"""

# ---------------------------------------------------------------------------
# 1. Master reset + instrument initialization
# ---------------------------------------------------------------------------

def reset_mfc_master(com_port: str) -> None:
    """
    If a propar master exists for this COM port, stop it and delete it.

    This mirrors the notebook logic that cleaned up propar._PROPAR_MASTERS
    before recreating instruments.
    """
    if hasattr(propar, "_PROPAR_MASTERS") and com_port in propar._PROPAR_MASTERS:
        master = propar._PROPAR_MASTERS[com_port]
        try:
            master.stop()
        except Exception as e:
            print(f"[MFC] Error stopping existing master on {com_port}: {e}")
        # Drop the old master so propar.instrument() creates a new one
        del propar._PROPAR_MASTERS[com_port]


def init_mfc_instruments(
    com_port: str,
    nodes: List[int],
    vessel: str,
    total_flow_rate: float,
    max_flow_rate: float,
) -> Dict[int, Any]:
    """
    Create and initialize Bronkhorst MFC instruments for given nodes.

    - Resets any old propar master on the COM port.
    - Creates a propar.instrument for each node.
    - Ensures the serial connection is open.
    - Sets slope off (parameter 10 = 0).
    - Sets initial setpoints corresponding to ppm=0 using ppm_to_sp(...).

    Returns:
        dict: {node: instrument}
    """
    reset_mfc_master(com_port)

    mfc: Dict[int, Any] = {}
    # ppm=0 → baseline setpoints for each node
    # setpoints = ppm_to_sp(ppm=0.0,vessel=vessel,max_flow_rate=max_flow_rate,
    #                       total_flow_rate=total_flow_rate,)

    for node in nodes:
        inst = propar.instrument(com_port, address=node)
        # Make sure COM is open
        if not inst.master.propar.serial.is_open:
            inst.master.start()  # opens COM port

        # Ensure that setpoint slope is off
        inst.writeParameter(10, 0)

        # Set initial setpoint to 0 sccm
        inst.writeParameter(9, 0)
        # inst.writeParameter(9,setpoints[node])
        
        # print ID and current flow
        try:
            mfc_id = inst.readParameter(1)
            current_flow = inst.readParameter(205)
            print(
                f"{com_port} node {node}: ID {mfc_id}, "
                f"current flow {current_flow:.3f} sccm"
            )
        except Exception as e:
            print(f"[MFC] Could not read ID/flow for node {node}: {e}")

        mfc[node] = inst

    return mfc


# ---------------------------------------------------------------------------
# 2. MFC thread: run protocol as fast as possible
# ---------------------------------------------------------------------------

class MFCThread(DeviceThread):
    """
    Thread controlling a single Bronkhorst MFC node according to a protocol.

    The protocol is defined as a list of segments:
        {'duration': seconds, 'ppm_start': x, 'ppm_end': y}

    For each segment, the thread linearly interpolates ppm from start to end,
    converts ppm -> per-node setpoints via ppm_to_sp, and writes setpoints
    to the given node as fast as possible. It also logs set & measured flows.
    """

    def __init__(
        self,
        node: int,
        inst: Any,
        stop_evt: threading.Event,
        logfile: PathLike,
        segments: List[Dict[str, float]],
        vessel: str = "NO2",
        total_flow_rate: float = 100.0,
        max_flow_rate: float = 50.0,
    ) -> None:
        super().__init__(stop_evt, name=f"MFCThread-{node}")
        self.node = node
        self.inst = inst
        self.logfile = Path(logfile)
        self.segments = segments
        self.vessel = vessel
        self.total_flow_rate = float(total_flow_rate)
        self.max_flow_rate = float(max_flow_rate)

    def run(self) -> None:
        # Prepare CSV
        self.logfile.parent.mkdir(parents=True, exist_ok=True)
        print(f"[MFCThread {self.node}] Logging to {self.logfile}")

        with self.logfile.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_iso", "set_sccm", "meas_sccm"])
            last_flush = time.time()

            # Global start time and first segment
            t0 = time.time()
            seg_idx = 0
            seg_start = t0

            seg = self.segments[0]
            duration = float(seg["duration"])
            ppm_start = float(seg["ppm_start"])
            ppm_end = float(seg["ppm_end"])

            # Set initial setpoint
            ppm_prev: Optional[float] = ppm_start
            setpoints = ppm_to_sp(
                ppm_start,
                vessel=self.vessel,
                max_flow_rate=self.max_flow_rate,
                total_flow_rate=self.total_flow_rate,
            )
            self.inst.writeParameter(9, setpoints[self.node])

            # Main loop: run through segments until done or stop_evt set
            while not self.stop_evt.is_set():
                now = time.time()
                seg_elapsed = now - seg_start

                # If this segment is complete, advance or finish
                if seg_elapsed >= duration:
                    seg_idx += 1
                    if seg_idx >= len(self.segments):
                        break  # protocol complete

                    seg = self.segments[seg_idx]
                    duration = float(seg["duration"])
                    ppm_start = float(seg["ppm_start"])
                    ppm_end = float(seg["ppm_end"])
                    seg_start = now
                    seg_elapsed = 0.0
                    ppm_prev = ppm_start

                # Compute current ppm (step or linear ramp)
                if ppm_start == ppm_end or duration == 0:
                    ppm_now = ppm_start
                else:
                    frac = seg_elapsed / duration
                    if frac < 0.0:
                        frac = 0.0
                    elif frac > 1.0:
                        frac = 1.0
                    ppm_now = ppm_start + (ppm_end - ppm_start) * frac

                # Convert ppm → raw setpoints for all nodes
                setpoints = ppm_to_sp(
                    ppm_now,
                    vessel=self.vessel,
                    max_flow_rate=self.max_flow_rate,
                    total_flow_rate=self.total_flow_rate,
                )

                # Only send new setpoint if ppm changed
                if ppm_prev is None or ppm_now != ppm_prev:
                    try:
                        self.inst.writeParameter(9, setpoints[self.node])
                    except Exception as e:
                        print(f"[MFCThread {self.node}] Error writing setpoint: {e}")
                        self.stop_evt.set()
                        break
                    ppm_prev = ppm_now

                # Read measured flow (parameter 8 is raw, scaled to sccm)
                try:
                    meas_raw = self.inst.readParameter(8)
                    meas_sccm = meas_raw / 32000.0 * self.max_flow_rate
                    set_sccm = setpoints[self.node] / 32000.0 * self.max_flow_rate
                except Exception as e:
                    print(f"[MFCThread {self.node}] Error reading flow: {e}")
                    self.stop_evt.set()
                    break

                # Log row
                w.writerow(
                    [
                        datetime.now().isoformat(timespec="milliseconds"),
                        f"{set_sccm:.3f}",
                        f"{meas_sccm:.3f}",
                    ]
                )

                # Only flush (batch write to the logfile) every ~20 s
                if time.time() - last_flush >= 20.0:
                    f.flush()
                    last_flush = time.time()

                # Tight loop, no intentional delay; just yield to scheduler
                time.sleep(0.0)

        # At the end, close the valve / stop master
        try:
            self.inst.writeParameter(9, 0)
        except Exception as e:
            print(f"[MFCThread {self.node}] Error closing valve: {e}")

        try:
            self.inst.master.stop()
        except Exception as e:
            print(f"[MFCThread {self.node}] Error stopping master: {e}")

        print(f"[MFCThread {self.node}] Protocol finished")

    


    
