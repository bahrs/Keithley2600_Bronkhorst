# src/kb_datalogger/protocol.py
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Dict, Any, Union, Optional
import json

PathLike = Union[str, Path]

'''
TODO: remove hardcoded values:
1) nodes = [7,8,9,11]
2) setpoint node 9
3) transfer MFC correction factors to the config file and add default values there
4) vessel concentration dict to config file
5) ppm resolution - move to readme?
6) include total flow rate and max flow rate to the segment? To the config file?
7) Default settle time to config file?
8) correct the gas usage calculation to use the config file values?
'''

def ppm_to_sp(
    ppm: float,
    vessel: str = "NO2",
    max_flow_rate: float = 50,
    total_flow_rate: float = 100,
) -> Dict[int, int]:
    """
    Convert ppm to setpoint in 0..32000 range.
    ppm: float - concentration in ppm [resolution - 0.002 ppm]
    vessel: str - 'NO2' or 'H2S'. Default 'NO2'.
    max_flow_rate: float - max flow rate of one MFC in sccm. Default 50 sccm.
    total_flow_rate: float - total flow rate in sccm. Default 100 sccm.
    
    NOTE: it is assumed and hardcoded that 
    1) nodes are [7,8,9,11]
    2) node 7 controls the target gas (NO2 or H2S)
    3) All MFC are calibrated the same way, with known correction factors from ppm to setpoint%.
    """
    vessel_dict = {'NO2': 100, 'H2S': 92}  # concentration in ppm
    mfc_correction_dict = {7: 0.5652, 8: 0.5663, 9: 0.5652, 11: 0.5660}  # correction factor for MFCs sccm per setpoint percent
    vessel_conc = vessel_dict[vessel]
    sccm = total_flow_rate * ppm / vessel_conc  # sccm
    setpoint_node7 = int(sccm / mfc_correction_dict[7] * 320 )
    setpoint_node8 = int((max_flow_rate - sccm) / mfc_correction_dict[8] * 320)
    setpoint_node9 = int(50 / mfc_correction_dict[9] * 320)
    setpoint_node11 = 0
    if (setpoint_node7 < 0 or setpoint_node7 > 32000) or (setpoint_node8 < 0 or setpoint_node8 > 32000):
        raise ValueError(f"Setpoint for node 7 or 8 is out of range: 7:{setpoint_node7}, 8:{setpoint_node8}")
    return {7: setpoint_node7, 8: setpoint_node8, 9: setpoint_node9, 11: setpoint_node11}


def segment_builder(
    ppm_start: float,
    ppm_end: float,
    speed: float | None,
    settle_time: float,
    total_flow_rate: float,
    max_flow_rate: float,
    vessel: str,
):
    """
    Build the segments for the MFCs based on the start and end ppm, speed, settle time, total flow rate, max flow rate and vessel.
    speed: float - speed in ppm/min
    settle_time: float - settle time in seconds
    """
    # Calculate the duration of the segment in seconds
    if ppm_start == ppm_end: 
        segment_duration = settle_time
    else:  
        segment_duration = abs(ppm_end - ppm_start) / speed * 60
    segment = {'duration': segment_duration, 'ppm_start': ppm_start, 'ppm_end': ppm_end}
    return [segment]

def one_cycle(
    ppm_start: float, 
    ppm_end: float, 
    speed: float, 
    settle_time: float, 
    total_flow_rate: float = 100.0, 
    max_flow_rate: float = 50.0, 
    vessel = 'NO2'
    ) -> Tuple[List[Dict], float]:
    """
    Build the segments for the MFCs based on the start and end ppm, speed, settle time, total flow rate, max flow rate and vessel.
    speed: float - speed in ppm/min
    settle_time: float - settle time in seconds
    """
    segments = segment_builder(ppm_start, ppm_start, speed = None, settle_time=settle_time, total_flow_rate = total_flow_rate, max_flow_rate = max_flow_rate, vessel = vessel)
    segments += segment_builder(ppm_start, ppm_end, speed = speed, settle_time=settle_time, total_flow_rate = total_flow_rate, max_flow_rate = max_flow_rate, vessel = vessel)
    segments += segment_builder(ppm_end, ppm_end, speed = None, settle_time=settle_time, total_flow_rate = total_flow_rate, max_flow_rate = max_flow_rate, vessel = vessel)
    segments += segment_builder(ppm_end, ppm_start, speed = speed, settle_time=settle_time, total_flow_rate = total_flow_rate, max_flow_rate = max_flow_rate, vessel = vessel)
    gas_usage = (sum([s['duration'] for s in segments]) * (ppm_end + ppm_start) / 2 / 60) * total_flow_rate / 100 / 1000 # in liters. 100 - NO2 vessel concentration in ppm
    return segments, gas_usage

def protocol_builder(
    ppm_start: float, 
    ppm_end: float, 
    speeds: list, 
    speed_repeat: int, 
    protocol_repeat: int = 1, 
    settle_time: float = 60.0, 
    total_flow_rate: float = 100.0, 
    max_flow_rate: str = 50, 
    vessel: str = 'NO2'
    ) -> List[Dict]:
    """
    Args:
        speeds: list - list of speeds in ppm/min
    Returns:
        segments: list - list of segments, where each segment is a dict with keys: {duration, ppm_start, ppm_end}
        NOTE: reported gas usage is hardcoded for NO2 vessel with 100 ppm concentration    
    """
    segments = []
    gas_usage = 0
    for speed in speeds:
        segment, gas_spent = one_cycle(ppm_start, ppm_end, speed, settle_time, total_flow_rate = total_flow_rate, max_flow_rate = max_flow_rate, vessel = vessel)
        segments += segment * speed_repeat
        gas_usage += gas_spent * speed_repeat
    segments *= protocol_repeat
    gas_usage *= protocol_repeat
    duration = int(sum([s['duration'] for s in segments]))
    print(f"Total time: {duration//3600} h {duration%3600//60} min \t\t Total gas usage: {gas_usage:.2f} L")
    return segments

# ---------------------------------------------------------------------------
# JSON export / import
# ---------------------------------------------------------------------------

def export_protocol_to_json(
    segments: List[Dict[str, float]],
    path: PathLike = "examples/example_protocol.json",
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Save protocol segments to a JSON file for reproducibility / inspection.

    Args:
        segments: list of segments as returned by protocol_builder()
        path: where to save the JSON (examples/example_protocol.json, etc.)
        meta: optional extra info (e.g. config params) stored under "meta"
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: Dict[str, Any] = {"segments": segments}
    if meta:
        payload["meta"] = meta

    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_protocol_from_json(path: PathLike) -> List[Dict[str, float]]:
    """
    Load protocol segments from a JSON file.

    Returns only the 'segments' list, which you can pass directly to MFCThread.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    # Support two shapes:
    #   {"segments": [...]}
    #   or directly [...]
    if isinstance(obj, dict) and "segments" in obj:
        segments = obj["segments"]
    else:
        segments = obj

    # (optional) sanity check: each segment has duration, ppm_start, ppm_end
    for i, seg in enumerate(segments):
        for key in ("duration", "ppm_start", "ppm_end"):
            if key not in seg:
                raise ValueError(f"Segment {i} is missing key '{key}': {seg}")

    return segments
