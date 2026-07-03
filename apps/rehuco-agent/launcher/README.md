# rehuco-agent dev launcher

Dev-only tooling (see `launcher.c`): a native Windows exe that embeds Python and runs
`rehuco_agent.__main__:main()` in-process against the workspace's live editable install. Gives
`.rehu` double-click/registration a real app identity (icon, `AppUserModelId`, taskbar pin)
without needing a Briefcase build. Never built, referenced, or shipped by `make qa`/`make
publish`, or a real Briefcase package.

A bare `uv`/pip console-script launcher has no PE icon resource and no `FileDescription`/
`ProductName` version metadata, so Explorer falls back to a generic icon and the raw exe
filename in the "how do you want to open this" picker; depending on how the launcher hands off
to Python, taskbar/AUMID identity can also resolve back to `python.exe` instead of the app.
`launcher.c` avoids all of this by embedding Python directly in a real, purpose-built,
icon-and-version-stamped exe. This is *not* the eventual end-user packaging story (that's
Briefcase, per §16.8) -- it's a dev-only stopgap.

See [§A02 in docs/specs](../../../docs/specs/appendices/windows-dev-launcher.md) for every
implementation hurdle hit building this launcher, and how each was solved.

## Prerequisites

- Visual Studio 2022 (or Build Tools) with the C++ workload.
- `cmake` on `PATH` -- prefer a recent one (§A05.1 explains why an old bundled CMake
  specifically breaks this). `scoop install cmake` is the recommended way to get one:

  ```sh
  scoop install cmake
  cmake --version   # confirmed working here at 4.3.4
  ```

- ImageMagick's `magick` on `PATH` (for `make icons`, a dependency of `make agent-register`).
  Tested working with `ImageMagick.Q8` -- both `ImageMagick.Q16` and `ImageMagick.Q16-HDRI` failed to run.

  ```sh
  winget install ImageMagick.Q8
  magick --version  # confirmed working here at 7.1.2-24 Q8
  ```

## Usage

```sh
make agent-build       # configure + build -> .build/apps/rehuco-agent/launcher/Release/rehuco-agent-dev.exe
make agent-register     # build, then --register (writes the .rehu HKCU association)
make agent-unregister   # --unregister
```

After `agent-register`, double-clicking a `.rehu` file routes through
`.build/apps/rehuco-agent/launcher/Release/rehuco-agent-dev.exe`. Source changes under
`apps/rehuco-agent/src` take effect on the next launch -- no rebuild needed unless
`launcher.c`/`CMakeLists.txt` themselves change. `make agent-build` is safe to run repeatedly:
it depends on the real output exe file (not a phony label), so it no-ops instantly once nothing
changed.
