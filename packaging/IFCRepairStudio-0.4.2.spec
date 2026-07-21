# -*- mode: python ; coding: utf-8 -*-
"""Audited windowed build for IFC Repair Studio 0.4.2.

The dependency list is deliberately narrow. PyInstaller's standard hooks discover
PySide6 and ReportLab; only IfcOpenShell's native/data payload needs explicit handling.
psutil is included only when the diagnostics extra is installed in the build venv.
"""
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


ROOT = Path(SPECPATH).parent
ICON = ROOT / "assets" / "ifc_repair_studio.ico"

datas = [(str(ICON), "assets")]
binaries = []
hiddenimports = ["ifcopenshell.validate"]

datas += collect_data_files("ifcopenshell")
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
        "OCC", "pytest", "_pytest", "unittest", "tkinter", "matplotlib",
        "IPython", "jupyter", "notebook", "numpy.testing", "setuptools.tests",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IFCRepairStudio-0.4.2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="IFCRepairStudio-0.4.2",
)
