"""
sysinfo.py - real system numbers for the JARVIS dashboard.

Only the standard library is used (ctypes talks to the Windows API), so nothing
extra has to be installed.

Every value can be None. The UI hides a tile when its value is None instead of
showing a made-up number. CPU temperature is the usual example: most PCs do not
expose it, so the tile simply disappears.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import socket
import subprocess
from pathlib import Path

IS_WINDOWS = os.name == "nt"
_GB = 1024 ** 3


def _percent(used: float, total: float) -> float:
    """used/total as a 0-100 number, rounded to one decimal."""
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * used / total)), 1)


# ---------------------------------------------------------------------------
# CPU (difference between two GetSystemTimes calls)
# ---------------------------------------------------------------------------
class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]


def _to_int(value) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


class CpuSampler:
    """CPU usage in percent, measured between two samples.

    The first call returns quickly by taking one short sample, so the dashboard
    never shows a fake 0% while the page is loading.
    """

    def __init__(self, first_sample_seconds: float = 0.12):
        self._first_sample_seconds = first_sample_seconds
        self._last: tuple[int, int, int] | None = None
        self._last_usage: float | None = None

    def _read(self) -> tuple[int, int, int] | None:
        if not IS_WINDOWS:
            return None
        try:
            idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
            ok = ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
        except Exception:  # never break the dashboard over a stat
            return None
        if not ok:
            return None
        return (_to_int(idle), _to_int(kernel), _to_int(user))

    def sample(self) -> float | None:
        current = self._read()
        if current is None:
            return None

        if self._last is None:
            self._last = current
            # One short blocking sample so the very first reading is real.
            import time

            time.sleep(self._first_sample_seconds)
            return self.sample()

        d_idle = current[0] - self._last[0]
        d_kernel = current[1] - self._last[1]
        d_user = current[2] - self._last[2]
        self._last = current

        # On Windows the kernel time already includes idle time.
        total = d_kernel + d_user
        if total <= 0:
            return self._last_usage
        self._last_usage = _percent(total - d_idle, total)
        return self._last_usage


# ---------------------------------------------------------------------------
# RAM
# ---------------------------------------------------------------------------
class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def memory() -> dict | None:
    """Physical memory in use, or None if the Windows call fails."""
    if not IS_WINDOWS:
        return None
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        used = stat.ullTotalPhys - stat.ullAvailPhys
        return {
            "percent": _percent(used, stat.ullTotalPhys),
            "used_gb": round(used / _GB, 2),
            "total_gb": round(stat.ullTotalPhys / _GB, 1),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def storage(path: str | None = None) -> dict | None:
    """Free/used space for the drive that holds JARVIS (usually C:)."""
    try:
        target = Path(path) if path else Path.home()
        root = target.anchor or str(target)
        usage = shutil.disk_usage(root)
        return {
            "percent": _percent(usage.used, usage.total),
            "used_gb": round(usage.used / _GB, 1),
            "free_gb": round(usage.free / _GB, 1),
            "total_gb": round(usage.total / _GB, 1),
            "drive": root,
        }
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Temperature (often unavailable - that is normal on desktops)
# ---------------------------------------------------------------------------
_WMI_TEMPERATURE_COMMAND = [
    "powershell",
    "-NoProfile",
    "-Command",
    "(Get-CimInstance -Namespace root/wmi "
    "-ClassName MSAcpi_ThermalZoneTemperature).CurrentTemperature",
]


def temperature() -> float | None:
    """CPU temperature in Celsius, or None when Windows does not expose one.

    Reads the ACPI thermal zone through PowerShell (built into Windows). Many
    motherboards do not publish this, so None is a normal, honest answer.
    """
    if not IS_WINDOWS:
        return None
    try:
        result = subprocess.run(
            _WMI_TEMPERATURE_COMMAND,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tenths_of_kelvin = float(line)
        except ValueError:
            continue
        celsius = round(tenths_of_kelvin / 10.0 - 273.15, 1)
        if -20.0 < celsius < 130.0:
            return celsius
    return None


# ---------------------------------------------------------------------------
# Host details
# ---------------------------------------------------------------------------
def host() -> dict:
    """Names and sizes that never change while the app runs."""
    return {
        "hostname": socket.gethostname(),
        "platform": os.name,
        "cores": os.cpu_count(),
        "python": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
    }
