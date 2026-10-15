"""Inherited pipes also work in PyInstaller's windowed macOS/Windows builds."""
import os


def binary_stdio(stream, *, output=False):
    if stream is not None:
        return getattr(stream, "buffer", stream)
    if os.name == "nt":
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_uint32]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel.GetStdHandle((-11 if output else -10) & 0xFFFFFFFF)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise OSError("The launcher did not provide a standard pipe")
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_WRONLY if output else os.O_RDONLY))
    else:
        fd = os.dup(1 if output else 0)
    return os.fdopen(fd, "wb" if output else "rb")
