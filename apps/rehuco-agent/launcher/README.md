# rehuco-agent dev launcher

Dev-only tooling (see `launcher.c`): a native Windows exe that embeds Python and runs
`rehuco_agent.__main__:main()` in-process against the workspace's live editable install. Gives
`.rehu` double-click/registration a real app identity (icon, `AppUserModelId`, taskbar pin)
without needing a Briefcase build. Never built, referenced, or shipped by `make qa`/`make
publish`, or a real Briefcase package.

## Prerequisites

- Visual Studio 2022 (or Build Tools) with the C++ workload.
- `cmake` on `PATH` -- `scoop install cmake` is the recommended way (confirmed working:
  `-G "Visual Studio 17 2022"` still finds and drives the same VS install regardless of which
  `cmake.exe` runs it). Qt also ships a CMake at `C:\Qt\Tools\CMake_64\bin`, not on `PATH` by
  default, as a fallback if you'd rather not add another scoop package -- either coexists fine,
  since CMake registers no system-wide state; whichever resolves first on `PATH` wins per
  invocation.
- ImageMagick's `magick` on `PATH` (for `make icons`, a dependency of `make agent-register`).

## Usage

```sh
make agent-build       # configure + build -> .build/apps/rehuco-agent/launcher/Release/rehuco-agent-dev.exe
make agent-register     # build, then --register (writes the .rehu HKCU association)
make agent-unregister   # --unregister
```

After `agent-register`, double-clicking a `.rehu` file routes through
`.build/apps/rehuco-agent/launcher/Release/rehuco-agent-dev.exe`. Source changes under
`apps/rehuco-agent/src` take effect on the next launch -- no rebuild needed unless
`launcher.c`/`CMakeLists.txt` themselves change.

## Known rough edges

- **First double-click after registering may show Explorer's "How do you want to open this
  file?" picker** rather than opening silently, even though the registration is correct --
  this is normal, expected Windows behavior for an extension with no prior `UserChoice`, not a
  registration bug. It should not recur once you've picked "Always" (or set it via **Settings →
  Apps → Default apps → search `.rehu`**, if your Windows build doesn't offer "Always" in the
  picker itself for brand-new extensions).
- **If `.rehu` has ever been associated with something else before** (e.g. an older prototype
  app), Explorer's per-extension history can get tangled -- wrong/missing icon, no "Always"
  option even on a supposedly fresh attempt, a picker that reappears despite choosing "Just
  once". If you hit this, reset Windows' own bookkeeping for the extension (not anything this
  project writes):

  ```powershell
  Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.rehu" -Recurse -Force
  ```

  This only clears Explorer's per-user MRU/choice tracking for `.rehu`; it does not touch this
  project's `HKCU:\Software\Classes` registration.
- **Icon or file-type label not updating after a fresh registration** is usually Explorer's
  icon-cache database, not a registration problem -- `SHChangeNotify` (called on every
  register/unregister) does not reliably flush it. Fix:

  ```powershell
  Stop-Process -Name explorer -Force
  Remove-Item "$env:LocalAppData\Microsoft\Windows\Explorer\iconcache_*.db" -Force -ErrorAction SilentlyContinue
  Start-Process explorer.exe
  ```

## Why an embedded launcher instead of the plain `uv`-generated `rehuco-agent.exe`

A bare `uv`/pip console-script launcher has no PE icon resource and no `FileDescription`/
`ProductName` version metadata, so Explorer falls back to a generic icon and the raw exe
filename in the "how do you want to open this" picker; depending on how the launcher hands off
to Python, taskbar/AUMID identity can also resolve back to `python.exe` instead of the app.
`launcher.c` avoids all of this by embedding Python directly in a real, purpose-built,
icon-and-version-stamped exe (ported from the `win-file-assoc-identity` spike, issue #1).

## CPython 3.14 venv-activation note

`config.executable`/`config.program_name`/the `__PYVENV_LAUNCHER__` environment variable --
the standard, documented mechanisms for a wrapper exe to activate a venv -- were not reliably
activating the workspace venv when embedding via `Py_InitializeFromConfig` on this CPython 3.14
build (confirmed environment-level: the pre-existing spike's own already-built exe exhibited
the identical failure, and recreating `.venv` from scratch made no difference). `launcher.c`
works around it directly: it calls `site.addsitedir()` on the venv's `site-packages` from the
entry script, which processes the editable-install `.pth` files without relying on venv
auto-activation at all.
