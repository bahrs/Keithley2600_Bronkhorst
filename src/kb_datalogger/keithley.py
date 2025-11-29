# src/kb_datalogger/keithley.py
import time
from typing import Tuple, Optional, Any

import pyvisa
from keithley2600 import Keithley2600

"""
Keithley 2601B helpers:
- initialization (driver object)
- connection check
- hard reset via PyVISA
- soft reset via driver
- high-level connect() with retry
- safe disconnect
- emergency VISA cleanup
"""

# ---------------------------------------------------------------------------
# 1. Low-level hard reset via PyVISA (no driver involved)
# ---------------------------------------------------------------------------

def hard_reset_keithley(
    address: str,
    visa_backend: str = "@ivi",
    wait_s: float = 15.0,
) -> None:
    """
    Low-level SCPI/TSP reset using only PyVISA.

    Used when the driver cannot connect, or when the instrument reports
    a wrong / empty IDN.

    This function:
    - opens the VISA resource
    - tries *IDN?
    - if IDN doesn't contain "Keithley", sends *RST;*CLS;system.reset()
    - closes the resource
    - waits for reboot
    """
    rm = pyvisa.ResourceManager(visa_backend)
    inst0 = rm.open_resource(address)
    inst0.timeout = 5000

    try:
        idn = inst0.query("*IDN?").strip()
        print(f"Keithley IDN: {idn}")
    except Exception as e:
        print("IDN failed:", e)
        idn = ""

    if "Keithley" not in idn:
        print("Instrument did not identify as Keithley – resetting via TSP/SCPI…")
        try:
            inst0.write("*RST;*CLS;system.reset()")
        except Exception as e:
            print("Reset command error:", e)

    inst0.close()
    rm.close()

    # Give it time to reboot
    if wait_s > 0:
        time.sleep(wait_s)

# ---------------------------------------------------------------------------
# 2. Initialization & connection check via driver
# ---------------------------------------------------------------------------

def init_keithley_driver(
    address: str,
    visa_library_path: str,
    raise_keithley_errors: bool = True,
) -> Keithley2600:
    """
    Create a Keithley2600 driver instance, but DO NOT connect yet.

    This is the "initialization" step: we simply construct the driver object.
    """
    k = Keithley2600(
        address,
        visa_library=visa_library_path,
        raise_keithley_errors=raise_keithley_errors,
    )
    return k


def check_keithley_connection(k: Keithley2600) -> bool:
    """
    Try to connect using the Keithley2600 driver and report whether it worked.

    This is the "connection checking" step. It:
    - calls k.connect()
    - inspects k.connected
    - prints the result
    - returns True/False

    If k.connect() itself fails, the exception is propagated to the caller,
    so that higher-level logic (e.g. retry with hard reset) can decide.
    """
    k.connect()
    connected = bool(getattr(k, "connected", False))
    print(f"Keithley connected: {connected}")
    return connected


# ---------------------------------------------------------------------------
# 3. Soft reset & configuration via driver
# ---------------------------------------------------------------------------

def soft_reset_keithley(
    k: Keithley2600,
) -> Any:
    """
    Soft reset via driver + configure integration time.

    This is the "soft reset" step. It:
    - resets the instrument via driver
    - resets SMU A
    - sets integration time
    - returns the smua object

    Returns:
        smu: the k.smua object, ready for measurements.
    """
    smu = k.smua
    k.reset()
    smu.reset()
    return smu


# ---------------------------------------------------------------------------
# 4. High-level connect with retry (uses all pieces above)
# ---------------------------------------------------------------------------

def connect_keithley_with_retry(
    address: str,
    visa_library_path: str,
    integration_time: float,
    max_retries: int = 2,
    visa_backend: str = "@ivi",
) -> Tuple[Keithley2600, Any]:
    """
    High-level helper that uses:
    - initialization (init_keithley_driver)
    - connection checking (check_keithley_connection)
    - hard reset (hard_reset_keithley)
    - soft reset (soft_reset_keithley)

    Logic:
    - For up to `max_retries` attempts:
        - initialize driver
        - try to connect and check `k.connected`
        - if connected: soft reset + configure, return (k, smu)
        - if not connected: hard reset via PyVISA and retry
    - If all attempts fail, raise RuntimeError.
    """
    last_exc: Optional[Exception] = None

    for attempt in range(max_retries):
        print(
            f"Connecting to Keithley at {address} "
            f"(attempt {attempt + 1}/{max_retries})"
        )

        try:
            # 1) initialization
            k = init_keithley_driver(address, visa_library_path)

            # 2) connection checking
            connected = check_keithley_connection(k)
            if not connected:
                print("Keithley driver reported connected=False; hard reset & retry.")
                hard_reset_keithley(address, visa_backend=visa_backend)
                continue

            # 3) soft reset + config
            smu = k.smua
            k.reset()
            smu.reset()
            k.set_integration_time(smu, integration_time)
            print("Keithley connected and configured.")
            return k, smu

        except Exception as e:
            last_exc = e
            print(f"Driver connect failed (attempt {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                print("-> performing hard reset and retrying…")
                hard_reset_keithley(address, visa_backend=visa_backend)
            else:
                break

    raise RuntimeError("Cannot connect to Keithley after reset attempts.") from last_exc


# ---------------------------------------------------------------------------
# 5. Disconnection / teardown
# ---------------------------------------------------------------------------

def disconnect_keithley(
    k: Keithley2600,
    smu: Optional[Any] = None,
) -> None:
    """
    Safely switch SMU output off and disconnect from the instrument.

    This is the "disconnection" step:
    - smu.output = smu.OUTPUT_OFF (if possible)
    - k.disconnect()
    """
    if smu is None:
        smu = getattr(k, "smua", None)

    if smu is not None:
        try:
            smu.output = smu.OUTPUT_OFF
        except Exception as e:
            print("Failed to switch SMU output off:", e)

    try:
        k.disconnect()
    except Exception as e:
        print("Failed to disconnect Keithley:", e)

# ---------------------------------------------------------------------------
# 6. Emergency cleanup of all VISA instruments (optional)
# ---------------------------------------------------------------------------

def cleanup_all_visa_instruments(visa_backend: str = "") -> None:
    """
    Emergency clean-up for stuck VISA sessions.

    This mirrors your "cleanup of bad session" notebook cell:
    - iterates over all VISA resources
    - best-effort *RST;*CLS and SMU reset commands
    - ignores unsupported commands / resources that can't be opened

    Use only when a previous session crashed and left instruments busy.
    """
    rm = pyvisa.ResourceManager(visa_backend) if visa_backend else pyvisa.ResourceManager()

    for res in rm.list_resources():
        try:
            inst = rm.open_resource(res)
            print(f"Resetting VISA resource {res}")
            # Not every instrument understands these, so we wrap each in try/except
            for cmd in ("*RST;*CLS", 
                        "smua.reset()", "smub.reset()", 
                        "smua.abort()", "smub.abort()", 
                        "smua.output = smua.OUTPUT_OFF", "smub.output = smub.OUTPUT_OFF", 
                        "system.reset()"):
                try:
                    inst.write(cmd)
                except Exception as e:
                    print(f"  Command {cmd} failed: {e}")
                    pass
            inst.close()
        except Exception:
            # Ignore resources we cannot open
            pass

    rm.close()