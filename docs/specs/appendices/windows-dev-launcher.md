# §A05. Windows Dev Launcher — Hurdles and Solutions

Engineering notes for the
[`apps/rehuco-agent/launcher/`](https://github.com/borco/rehuco/tree/master/apps/rehuco-agent/launcher)
dev launcher (see its
[`README.md`](https://github.com/borco/rehuco/blob/master/apps/rehuco-agent/launcher/README.md)
for what it *is* and how to use it) — every hurdle that took real time to work through while
building and hardening it past the `win-file-assoc-identity` spike (issue #1, closed; macOS
split to #13), so rebuilding a launcher like this (for this project or a future one) goes
faster.

Recorded in the order they actually bit, since later ones sometimes look like symptoms of
earlier ones until you've ruled the earlier fix out.

## §A05.1 CMake can't find Python (`Development.Embed`)

**Symptom:** `find_package(Python3 REQUIRED COMPONENTS Development.Embed)` fails with
`Could NOT find Python3 (missing: Python3_LIBRARIES Python3_INCLUDE_DIRS Development.Embed)`,
even with `Python3_EXECUTABLE`/`Python3_FIND_VIRTUALENV FIRST` hints set.

**Cause:** two compounding issues:

- Qt's bundled CMake (3.30, at `C:\Qt\Tools\CMake_64\bin`) predates Python 3.14's release, so
  its `FindPython3` module's name-based library search (`python313`, `python312`, ... down to
  `python30`) never tries `python314` and always misses, regardless of hints.
- `CMAKE_PREFIX_PATH` (which Qt's environment sets) shadows `Python3_EXECUTABLE`/
  `Python3_FIND_VIRTUALENV` hints in that same CMake version, so even pointing it at the right
  venv doesn't help.

**Fix:** install a recent CMake. `scoop install cmake` is the recommended way (confirmed
working at 4.3.4); `-G "Visual Studio 17 2022"` still finds and drives the same VS install
regardless of which `cmake.exe` runs it, so this doesn't conflict with anything else on the
machine. Qt also ships a CMake at `C:\Qt\Tools\CMake_64\bin`, not on `PATH` by default, as a
fallback if you'd rather not add another scoop package -- either coexists fine, since CMake
registers no system-wide state; whichever resolves first on `PATH` wins per invocation. Then
use the standard hint pattern:

```cmake
set(Python3_FIND_VIRTUALENV FIRST)
set(Python3_EXECUTABLE "${VENV_PYTHON}")
find_package(Python3 REQUIRED COMPONENTS Development.Embed)
```

If stuck on an old CMake with no option to upgrade it, the fallback is deriving the
include/library paths directly, bypassing `find_package`'s name-based search entirely:
query the venv Python for `sys.base_prefix` (a venv ships no headers/import lib of its own;
those live at the base install it was created from) and its `python3{minor}` library name, then
set `Python3_INCLUDE_DIR`/`Python3_LIBRARY`/`Python3_EXECUTABLE` as `CACHE ... FORCE` variables
before calling `find_package`.

## §A05.2 The compiled exe can't import the workspace's editable-installed packages

**Symptom:** the exe runs (no crash), but `ModuleNotFoundError: No module named 'rehuco_agent'`,
preceded by `<frozen site>:101: RuntimeWarning: Unexpected value in sys.prefix, expected
...\.venv, got ...\<base Python install>`.

**Cause:** `config.executable`/`config.program_name` (both set to the venv's `python.exe`), and
even the `__PYVENV_LAUNCHER__` environment variable -- the standard, documented mechanisms for
a wrapper exe to activate a venv -- did not reliably activate the workspace venv when embedding
via `Py_InitializeFromConfig` on this CPython 3.14 build. Confirmed environment-level, not a
mistake in this project's code: the `win-file-assoc-identity` spike's own already-built exe
(unmodified, previously verified working) exhibited the identical failure when re-run, and
recreating `.venv` from scratch made no difference either.

**Also ruled out:** placing the exe next to `.venv/` (matching the spike's own layout, on the
theory that CPython's path discovery favors a landmark next to the *running binary*) did **not**
fix it by itself -- the exe still failed identically from that location too. This red herring
cost real time; don't spend more of it re-testing exe placement.

**Fix:** stop relying on CPython's own venv auto-detection. Bake in the venv's `site-packages`
path (via a CMake-generated header) and call `site.addsitedir()` on it explicitly, from the
entry script run at startup:

```c
static const char *ENTRY_SCRIPT_FMT =
    "import sys, site\n"
    "site.addsitedir(r'%s')\n"
    "from rehuco_agent.__main__ import main\n"
    "sys.exit(main())\n";
```

`site.addsitedir()` (not a plain `sys.path.insert`) matters: it's what actually processes the
`.pth` files an editable install relies on. Once this works, the exe's build/output location
stops mattering at all -- confirmed working from both the repo root and a nested build
directory.

## §A05.3 A naive icon-generation build rule converts every SVG under `icons/` to its own `.ico`

**Symptom:** none yet observed in practice, but the bug is real: a pattern rule like
`%.ico: %.svg` combined with a broad glob over every SVG under any `icons/` directory will mint
a standalone `.ico` for *every* one -- including future toolbar/decorative SVGs that should
never become their own app icon.

**Fix:** there is exactly one app icon per app. Make the icon list an explicit path, not a glob.

Working `magick` invocation for a multi-resolution Windows icon:
`magick -background none <svg> -define icon:auto-resize=16,32,48,256 <ico>` (`-background none`
keeps it transparent rather than white-boxed).

## §A05.4 `make agent-build` re-runs `cmake` every time, even when nothing changed

**Symptom:** every invocation re-runs `cmake -S ...`/`cmake --build ...` in full, even though
CMake's own incremental build correctly no-ops internally (no recompile line in the output) --
the *wrapping* `make` invocation is the redundant part.

**Cause:** the target was declared `.PHONY`, so `make` has no file-based staleness check and
always re-invokes the recipe, regardless of whether CMake itself has anything to do.

**Fix:** make the actual output exe the real target, with real prerequisites (source files +
the icon).

**Trap inside the fix:** depend on the icon's real file path, *not* a phony `icons` label. A
real target depending on a `.PHONY` prerequisite is always considered out of date (phony
targets have no timestamp to compare), which silently defeats the whole point -- the exe target
would go back to rebuilding every time.

## §A05.5 Icon must exist *before* `cmake configure`, not just before registering

**Cause:** the `.rc` resource script embeds the `.ico` into the exe's PE resources at *build*
time (`configure_file` + the RC compiler step), not at registration time. Listing the icon as a
co-prerequisite of the thing that *uses* the launcher (the register step) does not guarantee it
exists before the build itself runs.

**Fix:** make icon generation a prerequisite of the build target directly, not of the
registration target.

## §A05.6 Explorer shows the raw exe filename, not a friendly app name, in the "open with" picker

**Cause:** the spike's `.rc` file only ever had `1 ICON "..."` -- no `VERSIONINFO` block.
Without a `FileDescription`, Explorer falls back to the literal filename.

**Fix:** add a `VERSIONINFO` resource block (`FileDescription`/`ProductName`/etc., under
`StringFileInfo`/`"040904b0"`) alongside the icon resource.

Also worth adding on top of the spike's plain `.ext` default-value binding: an
`OpenWithProgids` registry entry (`HKCU\Software\Classes\.<ext>\OpenWithProgids\<ProgID>` =
empty value), a stronger "this is a real recommended handler" signal for the picker.

## §A05.7 Explorer's "how do you want to open this" picker has no "Always" button, or reappears despite "Just once"

**Symptom:** registration is verifiably correct (checked the registry directly), the exe runs
and shows the right window, but Explorer's picker keeps reappearing on every double-click, and
"Always" isn't even offered.

**Cause, almost always:** the extension isn't actually new to Windows. `HKCU\Software\Microsoft\
Windows\CurrentVersion\Explorer\FileExts\.<ext>` is Explorer's *own* per-user bookkeeping,
separate from any app's `HKCU\Software\Classes` registration, and it accumulates history:
`OpenWithList` (every exe ever used to open the extension -- including unrelated older
prototype apps), `OpenWithProgids` (every ProgID ever associated, including an auto-generated
`<ext>_auto_file` entry Windows creates when something opens the file via "browse to an exe"
without a real ProgID), and critically `UserChoiceLatest`/`UserChoice` -- if a *stale* choice
points at an exe that no longer exists at its registered path, Explorer falls into a recovery
flow that suppresses "Always" to avoid a stuck loop.

**Fix:** reset Windows' own bookkeeping for the extension (not anything the app itself writes):

```powershell
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.<ext>" -Recurse -Force
```

This only clears Explorer's per-user MRU/choice tracking; it does not touch the app's own
`HKCU:\Software\Classes` registration, and Windows rebuilds it fresh on next use.

**If genuinely fresh** (extension really has never been used before) and there's still no
"Always" option: some Windows builds (particularly newer Insider/Canary ones) removed the
persistent "Always" choice from the first-encounter picker entirely, in favor of **Settings →
Apps → Default apps → search `<ext>`** as the only way to set a lasting default. Not a
registration bug either way.

## §A05.8 Icon or file-type label doesn't update after a fresh, correct registration

**Cause:** Explorer's icon-cache *database* (`iconcache_*.db`) is a separate cache from the
association cache `SHChangeNotify` refreshes, and doesn't reliably flush on its own.

**Fix:**

```powershell
Stop-Process -Name explorer -Force
Remove-Item "$env:LocalAppData\Microsoft\Windows\Explorer\iconcache_*.db" -Force -ErrorAction SilentlyContinue
Start-Process explorer.exe
```

## §A05.9 `PyConfig_SetArgv` drops the real `argv[0]`

Carried over correctly from the spike, but easy to reintroduce if rewriting from scratch:
`PyConfig_SetArgv` maps `config.argv` directly to `sys.argv`, but Python's own init consumes
`argv[0]` as the "interpreter name" and shifts everything else down -- so
`["launcher.exe", "file.rehu"]` in yields `sys.argv == ["file.rehu"]` out, silently losing
argv[0]. Fix: prepend an extra copy of `argv[0]` before calling `PyConfig_SetArgv`, so Python's
shift leaves the real `sys.argv` intact.

## §A05.10 AUMID must be set before any window (or `QApplication`) is constructed

Also carried over correctly from the spike: `SetCurrentProcessExplicitAppUserModelID` binds to
a process's first top-level HWND at *creation* time. Calling it after a window already exists
has no retroactive effect. Call it as literally the first statement in the launcher's entry
point, before Python initializes (which is itself before any Qt code can run).
