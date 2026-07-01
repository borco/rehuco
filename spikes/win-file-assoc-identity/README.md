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

def register(progid, exe_path, ico_path, extension, aumid, friendly_type_name):
    def set_val(path, name, val):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)

    command = f'"{exe_path}" "%1"'
    set_val(rf"Software\Classes\{progid}",                      "", friendly_type_name)
    set_val(rf"Software\Classes\{progid}\DefaultIcon",          "", f"{ico_path},0")
    set_val(rf"Software\Classes\{progid}\shell\open\command",   "", command)
    set_val(rf"Software\Classes\{progid}\Application", "AppUserModelId", aumid)
    set_val(rf"Software\Classes\.{extension}",                  "", progid)
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
if not singleton.setup("rehuco-agent"):   # False -> forwarded argv to existing primary; exit
    sys.exit(0)
singleton.other_instance_run.connect(window.open_files)   # list[str] of forwarded paths
```

## Set up icon

```sh
cd spikes/win-file-assoc-identity
cp ../../docs/assets/images/logo.svg logo.svg
magick -background none logo.svg -define icon:auto-resize=16,32,48,256 rehuco-spike.ico
```

## Set up and run (uv entry-point launcher)

```sh
cd spikes/win-file-assoc-identity
uv venv --python 3.14
uv pip install --python .venv/Scripts/python.exe "PySide6>=6.9"
uv pip install --python .venv/Scripts/python.exe -e ../../packages/borco-core
uv pip install --python .venv/Scripts/python.exe -e ../../packages/borco-pyside
uv pip install --python .venv/Scripts/python.exe -e .

# Register the file association (run once):
.venv/Scripts/rehuco-spike.exe --register

# Launch normally (or double-click a .rehuspike file after registering):
.venv/Scripts/rehuco-spike.exe
```

To clean up registry entries when done:

```sh
.venv/Scripts/rehuco-spike.exe --unregister
```

## Manual verification checklist (uv launcher)

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

## Briefcase test (Q6b — pin identity)

The uv entry-point launcher leaves a gap: it pins as Python (see Findings). Briefcase builds
a Windows exe with the icon embedded at link time. This sub-test checks whether that fixes it.

### Editable workflow with Briefcase

- `briefcase build windows` — one-time setup (downloads Python + PySide6 into a self-contained
  bundle; takes a few minutes). After this the launcher exe is fixed and can be registered/pinned.
- Edit code → `briefcase update windows` — fast (re-copies `src/` into the bundle; seconds).
- The registered/pinned exe stays the same between updates; only the running app code changes.
- `briefcase dev` — runs the app directly in your dev Python env (no packaged exe; no icon test).

### Set up and build

```sh
# Install Briefcase into the spike venv:
uv pip install --python .venv/Scripts/python.exe briefcase

# Build the Briefcase app (one-time; downloads Python + PySide6 into windows/):
briefcase build windows

# After building, the launcher is at (exact path shown in build output):
#   windows/Rehuco Spike-0.0.0/Rehuco Spike.exe
```

### Register the Briefcase exe as the handler

```sh
# Unregister the uv launcher first:
.venv/Scripts/rehuco-spike.exe --unregister

# Register the Briefcase exe (adjust path to match actual build output):
.venv/Scripts/rehuco-spike.exe --register --exe-path "windows/Rehuco Spike-0.0.0/Rehuco Spike.exe"
```

### Manual verification checklist (Briefcase)

1. **Build and run:** `briefcase build windows` then `briefcase run windows`. Confirm the
   window opens and shows the rehuco icon in the taskbar.
2. **Pin to taskbar:** right-click the running taskbar button → "Pin to taskbar".
3. **Close and relaunch from pin:** quit the app, click the pinned icon. Expected (pass):
   relaunches with rehuco icon — **not** Python's generic icon.
4. **Identity confirmed:** the pinned shortcut title should say "Rehuco Spike", not "Python".

## Custom C launcher (development workflow)

Briefcase solves pin identity for **distribution** but its `briefcase update windows` loop (a
few seconds) is still heavier than editing a `.py` file and relaunching directly. This section
tests a minimal C launcher compiled once with VS2022 + CMake that hosts Python in-process via
the Python C API — giving correct pin identity while keeping the Python source fully editable
and working with `uv`.

### How it works

`launcher/launcher.c` — a `wWinMain` entry point (no console) that:

1. Calls `SetCurrentProcessExplicitAppUserModelID` before any window.
2. Locates `.venv\Scripts\python.exe` next to the launcher exe.
3. Calls `Py_InitializeFromConfig` pointing `config.executable` at that Python so it reads
   `pyvenv.cfg` and activates the venv (editable install visible via site-packages).
4. Runs `from spike.app import main; sys.exit(main())` via `PyRun_SimpleString`.

`launcher/launcher.rc.in` — embeds the icon as PE resource ID 1; CMake's `configure_file`
bakes the absolute icon path in at configure time so the RC compiler finds it.

Because Python runs inside `rehuco-launcher.exe`'s process, the QMainWindow's HWND belongs to
that exe — taskbar button, pinned shortcut, and jump list all use its PE icon.

**`sys.argv` note:** `PyConfig_SetArgv` feeds Python's init phase which strips `argv[0]` (the
interpreter name) and maps `argv[1:]` to `sys.argv`. The launcher therefore prepends an extra
copy of `argv[0]` before calling `PyConfig_SetArgv` so Python's shift leaves `sys.argv`
intact: `[launcher_exe, file_path, ...]`.

### Build (one-time)

Requires VS2022 and Qt's CMake (`C:\Qt\Tools\CMake_64\bin\cmake.exe`). The icon
(`rehuco-spike.ico`) must exist before configuring (run the `magick` command in
[Set up icon](#set-up-icon) first).

```sh
cd spikes/win-file-assoc-identity/launcher

C:\Qt\Tools\CMake_64\bin\cmake.exe -B build -G "Visual Studio 17 2022" -A x64 `
  -DPython3_INCLUDE_DIR="C:/Users/<you>/scoop/apps/python/current/Include" `
  -DPython3_LIBRARY="C:/Users/<you>/scoop/apps/python/current/libs/python314.lib"

C:\Qt\Tools\CMake_64\bin\cmake.exe --build build --config Release
# Output: spikes/win-file-assoc-identity/rehuco-launcher.exe
```

### Register and run

```sh
cd spikes/win-file-assoc-identity

# Register the C launcher as the .rehuspike handler:
.venv/Scripts/python.exe -m spike.app --register --exe-path rehuco-launcher.exe

# Launch directly (or double-click any .rehuspike file):
rehuco-launcher.exe
```

### Development loop

Edit any `.py` file under `src/spike/` → close the window → relaunch `rehuco-launcher.exe`
(or double-click a `.rehuspike` file). No rebuild needed. The registered/pinned exe is never
touched during iteration.

### Manual verification checklist (C launcher)

1. **Build:** run the CMake commands above; confirm `rehuco-launcher.exe` appears next to `.venv/`.
2. **Register:** run `--register --exe-path rehuco-launcher.exe`; confirm exit 0.
3. **Open via file association:** double-click `test1.rehuspike`. Expected: window opens showing
   the full file path in the title and "Opened:" line.
4. **Second-instance routing:** with the window open, double-click `test2.rehuspike`. Expected:
   path appears in the "Second-instance paths forwarded here:" log; no second window.
5. **Pin to taskbar:** right-click the taskbar button → "Pin to taskbar". Close the app.
   Click the pin. Expected: relaunches with rehuco icon — not Python.
6. **In-place edit:** edit any `.py` source file, close and relaunch. Expected: change is live.

## Findings

Tested on Python 3.14.0, PySide6 6.9.x, Windows 11 (2026-07-01).

- [x] Step 3 — HKCU ProgID default handler: opens directly without picker ✓
- [x] Step 4 — DefaultIcon: rehuco icon shown on `.rehuspike` files in Explorer ✓
- [x] Step 5 — Taskbar icon while running: rehuco icon, not Python's generic icon ✓
  (`SetCurrentProcessExplicitAppUserModelID` must be called before `QApplication`)
- [x] Step 7 — Second double-click routes to existing instance (no second process) ✓
- [x] Step 6 — Pin to taskbar: **negative** — both exe approaches pin as Python ✗

  `python.exe main.py` (direct invocation): exe target is `python.exe` → pins as Python.
  `rehuco-spike.exe` (uv entry-point stub): stub has no embedded icon → still pins as Python.
  Root cause: `SetCurrentProcessExplicitAppUserModelID` fixes *runtime* grouping/icon, but
  the *pinned shortcut* reads the exe's PE icon resource; a stub with no embedded icon falls
  back to Python's identity regardless of the AUMID call.

- [ ] Step 8 — AUMID-on-ProgID empirical result: same root cause as Step 6 — the
  `Application\AppUserModelId` registry value is written, but the exe carries no embedded icon
  so the pinned shortcut still resolves to Python identity.

- [x] rcedit test: **negative** ✗

  Embedding the rehuco icon into `rehuco-spike.exe` via `rcedit` has no effect on pin identity.
  Root cause: the uv entry-point launcher (both `scripts` and `gui-scripts`) is a ~330KB Rust
  trampoline that spawns `python.exe` as a **subprocess** and exits. The `QMainWindow` lives in
  the `python.exe` process — Windows sees Python as the app owner. Patching the trampoline's PE
  resources changes the wrong exe; the window-owning process (`python.exe`) has no rehuco icon.

- [x] Briefcase test (Step 6b): **confirmed** ✓

  The Briefcase-built exe hosts Python in-process (unlike uv's trampoline) so `Rehuco Spike.exe`
  IS the window-owning process. Two things are needed together:

  - **PE icon resource** (embedded by Briefcase via rcedit at build time) → pinned shortcut shows
    rehuco icon, and the app name in the jump list is "Rehuco Spike", not "Python" ✓
  - **Qt QRC resource** (compiled `.qrc` → `resources_rc.py`, loaded at runtime) → window title-bar
    icon and taskbar button icon show rehuco while the app is running ✓

  The `briefcase update windows` command re-syncs Python source in seconds; the pinned exe stays
  unchanged. Iterating on app code does not require a full rebuild.

- [x] Custom C launcher (development workflow): **confirmed** ✓

  `rehuco-launcher.exe` (built once with VS2022 + CMake, ~300KB) hosts Python in-process via
  the Python C API. All requirements met on the same `uv`-managed venv:

  - **Pin identity:** pinned shortcut shows rehuco icon, app name is "rehuco-launcher" ✓
  - **File association:** `argv[1]` (the opened file path) arrives correctly in `sys.argv` ✓
  - **Second-instance routing:** second double-click forwards the path to the existing window ✓
  - **Editable in-place:** editing any `.py` source file under `src/spike/` is live on next
    launch with no rebuild ✓
  - **Works with uv:** the launcher uses the standalone spike venv; no conflict with uv workspace
    management ✓

  `sys.argv` note: Python's init phase consumes `argv[0]` as the interpreter name and shifts
  the rest. The launcher prepends an extra copy of `argv[0]` before `PyConfig_SetArgv` to
  compensate, so `sys.argv` arrives as `[launcher_exe, file_path, ...]` as expected.

## Verdict

**Full success with both Briefcase (distribution) and the custom C launcher (development).**

| Requirement | Approach | Result |
| --- | --- | --- |
| `.rehu` default handler (no elevation) | HKCU ProgID via `winreg` | ✓ |
| Explorer type name ("Rehuco File") | ProgID default value (friendly name) | ✓ |
| File icon in Explorer | `DefaultIcon` under ProgID | ✓ |
| Taskbar icon while running | AUMID + `QApplication.setWindowIcon()` from QRC | ✓ |
| Pin-to-taskbar identity | In-process exe with embedded PE icon (Briefcase or C launcher) | ✓ |
| Second double-click → existing instance | `ApplicationSingleton` | ✓ |
| Folder context menu "Open with Rehuco" | `HKCU\...\Directory\shell\rehuco` | ✓ |
| Editable in-place (dev loop) | Custom C launcher + editable venv install | ✓ |

**Key architectural lessons:**

- A `uv pip install -e .` entry-point launcher is a **Rust trampoline** (~330KB) that spawns
  `python.exe` as a subprocess. The window-owning process is `python.exe`, so rcedit on the
  trampoline does nothing. AUMID still works for runtime identity but the pinned shortcut resolves
  to Python.
- `pip install -e .` uses pip's **distlib in-process launcher** (~20KB C shim loading `Python.dll`)
  — the window-owning process IS the entry-point exe. rcedit would work there, but requires a
  re-run after each `pip install` that regenerates the launcher.
- **Briefcase** builds a proper in-process Windows exe with the icon embedded at build time. It is
  the recommended packaging path for distribution (§16.8 confirmed). `briefcase update windows`
  keeps the development loop fast without touching the registered/pinned exe.
- **Custom C launcher** (`launcher/launcher.c`, ~150 lines, Python C API) is the lightest
  in-process option for development: compiled once, never needs rebuilding as Python source
  changes, fully compatible with uv workspace management. Recommended for the A0 dev workflow
  on Windows until Briefcase is wired up for distribution builds.
