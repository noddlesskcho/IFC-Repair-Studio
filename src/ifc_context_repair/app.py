from __future__ import annotations

import sys


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "BCA.IFCRepairStudio.1"
        )
    except Exception:
        pass


def main() -> int:
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
    application.setApplicationName("IFC Repair Studio")
    icon = QIcon(str(resource_path("assets/ifc_repair_studio.ico")))
    application.setWindowIcon(icon)
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
