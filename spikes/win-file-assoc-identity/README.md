# Spike: Windows file association + app identity (ProgID, AUMID)

Throwaway spike for [#1](https://github.com/borco/rehuco/issues/1) (milestone `Pre-work`,
Windows half only — macOS half is out of scope for this pass).
**Keep the lesson (this README + the wiring snippet); delete `spikes/win-file-assoc-identity/` afterwards.**

## Decisions (2026-07-01)

- **Location:** top-level `spikes/win-file-assoc-identity/`, outside the uv workspace packages.
- **Environment:** a **throwaway venv local to this dir** (not added to any workspace `pyproject.toml`).
- **Branch:** `issue/1/win-file-assoc-identity`.
- **Extension:** `.rehuspike`, not `.rehu` — registering the real `.rehu` ProgID/UserChoice
  during a throwaway spike risks leaving the association pointing at a deleted venv; `.rehuspike`
  exercises the identical registry mechanism with zero collision risk.
- **AUMID:** `"Rehuco.Agent.Spike"` — a throwaway value. It does not pre-decide the production
  AUMID (that is Briefcase's job per §16.8).
- **Icon:** `docs/assets/images/logo.svg` copied locally and converted with ImageMagick (no
  custom conversion script, both files are gitignored and regenerable).
- **`borco-pyside`/`borco-core`:** installed as editable workspace packages (not pulled from
  PyPI) so the spike exercises current code.

## What it tests

1. **HKCU ProgID default handler** — double-clicking a `.rehuspike` file opens the spike
   window directly (no "How do you want to open this file?" picker), proving that registering
   `HKCU\Software\Classes\.rehuspike` → ProgID is sufficient as the unprivileged default
   handler when no `UserChoice` exists for the extension.
2. **DefaultIcon** — the `.rehuspike` file shows the rehuco icon in Explorer, not a blank
   document icon.
3. **AUMID taskbar identity** — the spike's taskbar button shows the rehuco icon, not the
   generic Python icon; pinning and re-launching preserves identity.
4. **Second double-click routes to existing instance** — a second `.rehuspike` double-click
   while the spike is running does not open a second window; the forwarded path appears in the
   existing window's log (via `ApplicationSingleton.other_instance_run`).

## The reference wiring (the bit worth keeping)

### AUMID before QApplication

```python
import ctypes, sys
from PySide6.QtWidgets import QApplication

# Must be first — Windows binds AUMID to the process's first top-level HWND at
# creation time; calling this after a window exists has no retroactive effect.
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Rehuco.Agent")

app = QApplication(sys.argv)
# ... build and show window ...
```

### HKCU ProgID registration (minimal)

```python
import winreg, ctypes

def register(progid, python_exe, script, ico_path, extension, aumid):
    def set_val(path, name, val):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)

    command = f'"{python_exe}" "{script}" "%1"'
    set_val(rf"Software\Classes\{progid}\DefaultIcon",        "", f"{ico_path},0")
    set_val(rf"Software\Classes\{progid}\shell\open\command", "", command)
    set_val(rf"Software\Classes\{progid}\Application", "AppUserModelId", aumid)
    set_val(rf"Software\Classes\.{extension}",                "", progid)
    # tell Explorer immediately — no logoff needed
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
```

Note: do **not** attempt to write `FileExts\.<ext>\UserChoice` — it is protected by a hash
Explorer computes itself and is blocked on current Windows. The plain `.ext` default-value
ProgID approach works fine for a fresh extension with no existing `UserChoice`.

### ApplicationSingleton (second-instance routing)

```python
from borco_pyside.core.application_singleton import ApplicationSingleton

singleton = ApplicationSingleton()
if not singleton.setup("rehuco-agent"):   # False → forwarded argv to existing primary; exit
    sys.exit(0)
singleton.other_instance_run.connect(window.open_files)   # list[str] of forwarded paths
```

## Set up icon

```sh
cd spikes/win-file-assoc-identity
cp ../../docs/assets/images/logo.svg logo.svg
magick -background none logo.svg -define icon:auto-resize=16,32,48,256 rehuco-spike.ico
```

## Set up and run

```sh
cd spikes/win-file-assoc-identity
uv venv --python 3.14
uv pip install --python .venv/Scripts/python.exe "PySide6>=6.9"
uv pip install --python .venv/Scripts/python.exe -e ../../packages/borco-core
uv pip install --python .venv/Scripts/python.exe -e ../../packages/borco-pyside

# Register the file association (run once):
.venv/Scripts/python.exe main.py --register

# Launch normally (or double-click a .rehuspike file after registering):
.venv/Scripts/python.exe main.py
```

To clean up registry entries when done:

```sh
.venv/Scripts/python.exe main.py --unregister
```

## Manual verification checklist

These steps cannot be automated — they require driving Windows Explorer by hand.

1. **Register:** run `--register`, confirm exit code 0 and no traceback.
2. **Create a test file:** create `test.rehuspike` anywhere in Explorer (empty file is fine).
3. **Default handler (no prior UserChoice):** double-click `test.rehuspike`. Expected: spike
   window opens directly — no "How do you want to open this file?" picker.
4. **File icon in Explorer:** look at `test.rehuspike` in Large Icon or Details view. Expected:
   rehuco icon, not a blank-document generic.
5. **Taskbar icon while running:** check the taskbar button with the spike open. Expected:
   rehuco icon, not the generic Python/terminal icon.
6. **Pin to taskbar:** right-click the running taskbar button → "Pin to taskbar". Close the
   app. Click the pinned icon. Expected: relaunches correctly with the same icon.
7. **Second double-click → existing instance:** with the spike running, double-click a second
   `test2.rehuspike` in Explorer. Expected: no second window appears; the existing window's log
   shows the forwarded path. Confirm via Task Manager that only one python.exe process exists.
8. **AUMID-on-ProgID empirical check (open question — observe, don't assert):** with the app
   pinned (step 6), fully quit the running instance (nothing has called
   `SetCurrentProcessExplicitAppUserModelID` yet), then relaunch from the pinned shortcut.
   Record the actual taskbar grouping/icon behavior observed in Findings below.
9. **Unregister:** run `--unregister`. Spot-check with
   `reg query HKCU\Software\Classes\.rehuspike` — should return "not found". Double-clicking
   `test.rehuspike` should no longer open the spike.

## Findings

*Fill in after running the manual checklist.*

- [ ] Q1 HKCU ProgID default handler — opens directly without picker
- [ ] Q2 DefaultIcon — rehuco icon shown on `.rehuspike` files in Explorer
- [ ] Q3 Taskbar icon — rehuco icon, not Python's generic icon
- [ ] Q4 Second double-click routes to existing instance (no second process)
- [ ] Q8 AUMID-on-ProgID empirical result (pin → quit → relaunch from pin):

## Verdict

*To be filled in after Findings.*
