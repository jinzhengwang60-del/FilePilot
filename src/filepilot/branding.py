"""Application identity and icons, shared by source and packaged Windows builds."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

APP_USER_MODEL_ID = "FilePilot.Desktop"


def application_icon():
    from PySide6.QtGui import QIcon
    return QIcon(str(Path(__file__).with_name("assets") / "filepilot.ico"))


def configure_windows_identity() -> None:
    if os.name != "nt":
        return
    # Set before creating any UI so Python-hosted and frozen windows group as FilePilot.
    setter = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_long
    result = setter(APP_USER_MODEL_ID)
    if result < 0:
        raise OSError(result, "Windows could not assign the FilePilot application identity")


def current_windows_identity() -> str | None:
    if os.name != "nt":
        return None
    getter = ctypes.WinDLL("shell32").GetCurrentProcessExplicitAppUserModelID
    getter.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
    getter.restype = ctypes.c_long
    pointer = ctypes.c_wchar_p()
    result = getter(ctypes.byref(pointer))
    if result < 0:
        return None
    try:
        return pointer.value
    finally:
        free = ctypes.WinDLL("ole32").CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        free(ctypes.cast(pointer, ctypes.c_void_p))
