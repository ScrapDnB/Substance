"""Platform conventions that stay outside the document/editor model."""
import ctypes
import subprocess
import sys


def reduce_motion() -> bool:
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["/usr/bin/defaults", "read", "com.apple.universalaccess", "reduceMotion"], capture_output=True, text=True, timeout=1)
            return result.stdout.strip().lower() in ("1", "true", "yes")
        if sys.platform == "win32":
            enabled = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
            return not bool(enabled.value)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False
