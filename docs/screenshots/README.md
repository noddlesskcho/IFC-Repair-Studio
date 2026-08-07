# IFC+SG Repair Assistant UI states

These screenshots are rendered from the production `MainWindow` class using a
deterministic display-only report. No alternate mock-up UI is used.

1. `01-select-ifc.png` — initial state
2. `02-selected-ifc.png` — IFC selected
3. `03-checking-ifc.png` — audit in progress
4. `04-results-ready.png` — production-safe repairs and experimental findings
5. `05-unsupported-file.png` — audit available, automatic repair disabled
6. `06-repairing-ifc.png` — repaired IFC being saved and verified
7. `07-repair-completed.png` — successful production repair
8. `08-no-issues-detected.png` — supported issue not detected
9. `09-audit-completed.png` — Audit Only completion
10. `10-repair-failed.png` — safe failure with original IFC preserved
11. `11-compatibility-test-mode.png` — isolated compatibility-output warning
12. `12-compatibility-tests-completed.png` — compatibility matrix completed

Regenerate with:

```powershell
python scripts\capture_ui_states.py
```
