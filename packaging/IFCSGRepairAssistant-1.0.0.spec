# -*- mode: python ; coding: utf-8 -*-
"""Production windowed build for IFC+SG Repair Assistant 1.0.0."""
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


ROOT = Path(SPECPATH).parent
ICON = ROOT / "assets" / "ifc_repair_studio.ico"
VERSION = ROOT / "packaging" / "version_info.txt"

datas = [
    (str(ICON), "assets"),
    (str(ROOT / "assets" / "THIRD_PARTY_NOTICES.txt"), "assets"),
    (str(ROOT / "assets" / "rules_ifc_sg.json"), "assets"),
    (str(ROOT / "LICENSE"), "."),
]
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
    name="IFCSGRepairAssistant-1.0.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON),
    version=str(VERSION),
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
