# IFC+SG Repair Assistant UI states

These screenshots are rendered from the production `MainWindow` class using a
deterministic display-only report. No alternate mock-up UI is used.

1. `01-select-ifc.png` — initial state
2. `02-selected-ifc.png` — IFC selected
3. `03-checking-ifc.png` — audit in progress
4. `04-results-ready.png` — supported file with repairs available
5. `05-unsupported-file.png` — audit available, automatic repair disabled
6. `06-repairing-ifc.png` — repaired IFC being saved and verified
7. `07-repair-completed.png` — successful completion
8. `08-no-issues-detected.png` — supported issue not detected
9. `09-audit-completed.png` — Audit Only completion
10. `10-repair-failed.png` — safe failure with original IFC preserved

Regenerate with:

```powershell
python scripts\capture_ui_states.py
```
