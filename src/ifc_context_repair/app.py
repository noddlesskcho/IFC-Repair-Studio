from __future__ import annotations

import sys

from . import __version__


_INSTANCE_MUTEX: object | None = None


def _acquire_single_instance() -> bool:
    """Hold a Windows named mutex so accidental duplicate GUIs exit immediately."""
    global _INSTANCE_MUTEX
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(
            None, False, "Local\\BCA.IFCSGRepairAssistant.SingleInstance"
        )
        if not handle:
            return True
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _INSTANCE_MUTEX = handle
    except Exception:
        # Single-instance protection must never prevent repair when unavailable.
        return True
    return True


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "BCA.IFCSGRepairAssistant.1.0"
        )
    except Exception:
        pass


def main() -> int:
    if not _acquire_single_instance():
        return 0
    _set_windows_app_id()
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is required for the desktop app. Install with: pip install -e .[ui]",
              file=sys.stderr)
        return 4
    from .ui.main_window import MainWindow
    from .resources import resource_path

    application = QApplication(sys.argv)
    application.setApplicationName("IFC+SG Repair Assistant")
    application.setApplicationVersion(__version__)
    icon = QIcon(str(resource_path("assets/ifc_repair_studio.ico")))
    application.setWindowIcon(icon)
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
