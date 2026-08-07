# -*- mode: python ; coding: utf-8 -*-
"""Windowed Version 1 build: direct-product repair only by default."""
from importlib.util import find_spec
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


ROOT = Path(SPECPATH).parent
ICON = ROOT / "assets" / "ifc_repair_studio.ico"

# Android Studio adds its private JBR directory to the machine PATH.  Its
# api-ms-win-* compatibility DLLs are not Windows redistributables and must
# never become application binaries.  Sanitise PATH before Analysis resolves
# dependent DLLs; the build script applies the same protection for PyInstaller
# startup itself.
_path_parts = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
_path_parts = [
    part for part in _path_parts
    if not (
        "android studio" in part.casefold()
        and ("jbr" in part.casefold() or "jre" in part.casefold())
    )
]
_windows_paths = [
    str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"),
    os.environ.get("SystemRoot", r"C:\Windows"),
]
os.environ["PATH"] = os.pathsep.join(dict.fromkeys(_windows_paths + _path_parts))


def _keep_ifcopenshell_data(entry):
    source, destination = entry
    combined = f"{source}/{destination}".replace("\\", "/").casefold()
    return not (
        "/simple_spf/fixtures/" in combined
        or "/mvd/mvd_examples/" in combined
        or combined.endswith("/express/run.bat/ifcopenshell/express")
        or source.replace("\\", "/").casefold().endswith("/express/run.bat")
    )


def _is_pyside_translation(entry):
    if len(entry) == 2:
        source, destination = entry
    else:
        destination, source, _typecode = entry
    combined = f"{source}/{destination}".replace("\\", "/").casefold()
    return combined.endswith(".qm") and "pyside6" in combined


_UNUSED_QT_RUNTIME_NAMES = {
    "qt6network.dll",
    "qt6opengl.dll",
    "qt6pdf.dll",
    "qt6qml.dll",
    "qt6qmlmeta.dll",
    "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll",
    "qt6quick.dll",
    "qt6virtualkeyboard.dll",
}


def _is_unused_qt_binary(entry):
    if len(entry) == 2:
        source, destination = entry
    else:
        destination, source, _typecode = entry
    destination_normalized = str(destination).replace("\\", "/").casefold()
    source_name = Path(str(source)).name.casefold()
    return (
        source_name in _UNUSED_QT_RUNTIME_NAMES
        or destination_normalized.endswith(
            "/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll"
        )
        or destination_normalized.endswith("/plugins/imageformats/qpdf.dll")
    )


datas = [
    (str(ICON), "assets"),
    (str(ROOT / "assets" / "rules_ifc_sg.json"), "assets"),
    (str(ROOT / "assets" / "repair_signature_status.json"), "assets"),
    (str(ROOT / "assets" / "THIRD_PARTY_NOTICES.txt"), "assets"),
    (str(ROOT / "LICENSE"), "."),
]
binaries = []
hiddenimports = ["ifcopenshell.validate"]
datas += [
    entry for entry in collect_data_files("ifcopenshell")
    if _keep_ifcopenshell_data(entry)
]
binaries += collect_dynamic_libs("ifcopenshell")
if find_spec("psutil") is not None:
    datas += collect_data_files("psutil")
    binaries += collect_dynamic_libs("psutil")
    hiddenimports.append("psutil")

a = Analysis(
    [str(ROOT / "scripts" / "gui_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "OCC", "pytest", "_pytest", "tkinter", "matplotlib", "IPython",
        "jupyter", "notebook", "setuptools.tests",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtVirtualKeyboard",
        "PySide6.QtPdf", "PySide6.QtNetwork", "PySide6.QtOpenGL",
        "numpy._core._multiarray_tests", "numpy.fft", "numpy.random",
        # numpy.linalg is required while IfcOpenShell imports numpy.matrixlib.
        "numpy.testing",
        # asyncio/Qt paths may use the thread executor, but this application
        # never uses ProcessPoolExecutor or multiprocessing.
        "concurrent.futures.process", "multiprocessing",
    ],
    noarchive=False,
    optimize=1,
)

# Qt hooks discover translations during Analysis, so filter them afterwards.
# The application is English-only and does not install translators.
a.datas = [entry for entry in a.datas if not _is_pyside_translation(entry)]
a.binaries = [entry for entry in a.binaries if not _is_unused_qt_binary(entry)]

_jbr_binaries = [
    entry for entry in a.binaries
    if "android studio" in str(entry[1]).casefold()
    and ("jbr" in str(entry[1]).casefold() or "jre" in str(entry[1]).casefold())
]
if _jbr_binaries:
    raise RuntimeError(
        "Unsafe Android Studio JBR DLLs were selected for packaging: "
        + ", ".join(str(entry[1]) for entry in _jbr_binaries[:5])
    )

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IFCSGRepairAssistant-1.0.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="IFCSGRepairAssistant-1.0.0",
)

# PyInstaller reports intentionally excluded lazy NumPy namespaces as
# "excluded module" entries.  They are not missing dependencies, so keep the
# developer warning report focused on actionable and genuinely optional items.
from PyInstaller.config import CONF

_warnfile = Path(CONF["warnfile"])
if _warnfile.exists():
    _intentional_numpy_exclusions = (
        "excluded module named numpy.fft ",
        "excluded module named numpy.random ",
    )
    _warn_lines = _warnfile.read_text(encoding="utf-8").splitlines(keepends=True)
    _warnfile.write_text(
        "".join(
            line for line in _warn_lines
            if not line.startswith(_intentional_numpy_exclusions)
        ),
        encoding="utf-8",
    )
