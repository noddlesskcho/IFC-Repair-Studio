# Windows Build Instructions — Version 1.0

## Requirements

- Windows 10 or 11, 64-bit
- Python 3.12, 64-bit
- Enough disk for the environment, PyInstaller work directory and executable

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[ui,test,build,diagnostics]"
python -m pytest -q
python -m PyInstaller --noconfirm --clean packaging\IFCSGRepairAssistant-1.0.0.spec
```

Output:

```text
dist\IFCSGRepairAssistant-1.0.0\IFCSGRepairAssistant-1.0.0.exe
```

The adjacent `_internal` directory is part of the application and must remain
beside the executable.

The spec bundles the icon, Windows version metadata, license, third-party
notices, IFC+SG rule metadata, Qt runtime, ReportLab/Pillow and IfcOpenShell
native/data files. psutil is included when installed by the diagnostics extra.

Release validation requires:

1. test suite;
2. no required-runtime missing-module warning;
3. executable launch smoke test;
4. small IFC end-to-end repair/report test;
5. large regression verification;
6. SHA-256 publication.

## Packaged release self-test

Release engineering can exercise the frozen production stack without opening
the UI:

```powershell
.\dist\IFCSGRepairAssistant-1.0.0\IFCSGRepairAssistant-1.0.0.exe `
  --self-test C:\path\input.ifc C:\path\output.ifc advanced
```

This diagnostic switch is not a second supported user workflow. It returns a
process exit code and writes an adjacent `_self_test.json` evidence file. It
uses the same repair, verification, reporting, and logging implementation as
the GUI.

See `pyinstaller-warning-classification-v1.0.md` for the reviewed warning list.
