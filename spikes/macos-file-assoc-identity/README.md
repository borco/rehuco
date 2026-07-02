# Spike: macOS file association + app identity (.app/QFileOpenEvent, single-instance)

Throwaway spike for [#13](https://github.com/borco/rehuco/issues/13) (milestone `A0`, macOS
half of the file-association spike; the Windows half closed in
[#1](https://github.com/borco/rehuco/issues/1)/`spikes/win-file-assoc-identity/`, since removed).
**Keep the lesson (this README + the wiring snippet); delete `spikes/macos-file-assoc-identity/`
afterwards.**

## Decisions (2026-07-02)

- **Location:** top-level `spikes/macos-file-assoc-identity/`, outside the uv workspace packages.
- **Environment:** a **throwaway venv local to this dir** (not added to any workspace `pyproject.toml`).
- **Branch:** `issue/13/macos-file-assoc-spike`.
- **Extension:** `.rehuspike`, not `.rehu` — registering the real `.rehu` UTI during a throwaway
  spike risks leaving LaunchServices pointed at a deleted `.app`; `.rehuspike` exercises the
  identical UTI/`CFBundleDocumentTypes` mechanism with zero collision risk.
- **Bundle ID:** `com.borco.rehuco.spike` — a throwaway value; it does not pre-decide the
  production bundle ID.
- **Icon:** `docs/assets/images/logo.svg` copied locally and converted to `.icns` with
  `sips`/`iconutil` (both gitignored and regenerable).
- **`borco-pyside`/`borco-core`:** installed as editable workspace packages (not pulled from
  PyPI) so the spike exercises current code.
- **Packager:** Briefcase, per §16.8's decision — a real UTI/`CFBundleDocumentTypes` declaration
  requires an actual `.app` bundle; there is no non-bundle way to register a macOS document type.

## What it tests

1. **A minimal Briefcase `.app` registers `.rehuspike` as a document type** — `LSItemContentTypes`
   / `UTExportedTypeDeclarations` claim a custom UTI, and `mdls -name kMDItemContentType` on a
   `.rehuspike` file resolves to it.
2. **`QFileOpenEvent` delivers the path** — opening a `.rehuspike` file (via Finder-equivalent
   `open <file>`, using the extension alone, no `-a`) launches the app and the path arrives via
   `QFileOpenEvent`, not `argv`.
3. **Second open routes to the existing instance** — opening a second `.rehuspike` file while the
   app is running does not spawn a second process.

## The reference wiring (the bit worth keeping)

### Briefcase document-type config (`pyproject.toml`)

```toml
[tool.briefcase.app.spike.document_type.rehuspike]
description = "Rehuco Spike File"
extension = "rehuspike"
icon = "rehuco-spike"
url = "https://github.com/borco/rehuco"
mime_type = "application/x-rehuco-spike"

[tool.briefcase.app.spike.macOS]
requires = ["std-nslog~=2.0.0"]
# PySide6's macOS wheel is macosx_13_0_universal2; Briefcase's 11.0 default is too low.
min_os_version = "13.0"
```

Briefcase turns this into both `CFBundleDocumentTypes` (so Finder/LaunchServices show it as a
document type with the right icon) and `UTExportedTypeDeclarations` (so `mdls` / Spotlight / any
UTI-aware API resolve the extension to a concrete type) — no manual `Info.plist` editing needed.
Local (non-PyPI) workspace dependencies go straight into `requires` as relative paths:

```toml
requires = ["PySide6>=6.9", "../../packages/borco-core", "../../packages/borco-pyside"]
```

### `QFileOpenEvent` (macOS double-click delivery)

```python
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

class Application(QApplication):
    def event(self, event: QEvent) -> bool:
        if isinstance(event, QFileOpenEvent):
            self.window.append_opened(event.file())
            return True
        return super().event(event)
```

macOS does **not** pass a double-clicked path as `argv`; it arrives as this Cocoa-originated Qt
event instead. `main()` still checks `sys.argv[1:]` too, for parity with Windows' `argv`-based
forwarding (§5.4) and for `python -m spike <path>` during development.

### `ApplicationSingleton` (second-instance routing, fallback path)

```python
from borco_pyside.core.application_singleton import ApplicationSingleton

app = Application(sys.argv)
singleton = ApplicationSingleton()
if not singleton.setup(APP_ID):   # False -> forwarded argv to existing primary; exit
    sys.exit(0)
singleton.other_instance_run.connect(app.window.append_forwarded)
```

Same `QLocalServer`/`QLocalSocket` mechanism as Windows (§5.4) — unchanged, no macOS-specific
code needed here. See **Findings** below for when this path actually fires on macOS.

## Set up icon

```sh
cd spikes/macos-file-assoc-identity
cp ../../docs/assets/images/logo.svg logo.svg
magick -background none logo.svg -resize 1024x1024 rehuco-spike-1024.png
mkdir icon.iconset
for size in 16 32 64 128 256 512; do
  sips -z $size $size rehuco-spike-1024.png --out "icon.iconset/icon_${size}x${size}.png"
  double=$((size*2))
  sips -z $double $double rehuco-spike-1024.png --out "icon.iconset/icon_${size}x${size}@2x.png"
done
iconutil -c icns icon.iconset -o rehuco-spike.icns
rm -rf icon.iconset rehuco-spike-1024.png
```

## Set up and build

```sh
cd spikes/macos-file-assoc-identity
uv venv --python 3.14
uv pip install --python .venv/bin/python "PySide6>=6.9"
uv pip install --python .venv/bin/python -e ../../packages/borco-core
uv pip install --python .venv/bin/python -e ../../packages/borco-pyside
uv pip install --python .venv/bin/python -e .
uv pip install --python .venv/bin/python briefcase

briefcase build macOS
# Output: build/spike/macos/app/Rehuco Spike.app
```

Iterate on app code with `briefcase update macOS` (fast; re-syncs `src/` into the bundle) instead
of a full rebuild.

## Manual verification (driven from the terminal — no Finder/screen-sharing needed)

`open` and `lsregister` drive the exact same LaunchServices path Finder does for a double-click,
so this was verified entirely over SSH with no GUI session attached.

```sh
LSREG=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister

# Register the built .app with LaunchServices (Finder does this automatically on first launch/copy):
"$LSREG" -f "build/spike/macos/app/Rehuco Spike.app"

# Confirm the UTI is claimed and our .app is the Owner:
"$LSREG" -dump | grep -A6 "com.borco.rehuco.spike.rehuspike"

# Confirm a fresh .rehuspike file resolves to our UTI:
echo test > /tmp/test.rehuspike
mdls -name kMDItemContentType /tmp/test.rehuspike   # -> com.borco.rehuco.spike.rehuspike

# Open it exactly like a Finder double-click would (extension alone, no -a):
open /tmp/test.rehuspike

# Watch delivery + routing live:
log stream --style compact --predicate 'process == "Rehuco Spike"'
```

## Findings

Tested on Python 3.14.6, PySide6 6.11.1, Briefcase 0.4.3, macOS 26.5.1 (2026-07-02).

- [x] **UTI/`CFBundleDocumentTypes` registration** ✓

  Briefcase generated both `CFBundleDocumentTypes` and `UTExportedTypeDeclarations` correctly
  from the `document_type.rehuspike` config — no hand-edited `Info.plist`. `lsregister -dump`
  shows `Rehuco Spike` as `rank: Owner` for `com.borco.rehuco.spike.rehuspike`, and `mdls` on a
  fresh `.rehuspike` file resolves to that UTI.

- [x] **`QFileOpenEvent` delivery** ✓

  `open /tmp/test.rehuspike` (extension-only, the same LaunchServices path Finder uses) launched
  the app; the log shows `spike.app: opened: /private/tmp/test.rehuspike` — delivered through
  `Application.event()`'s `QFileOpenEvent` branch, confirmed **not** via `argv` (macOS launches a
  LaunchServices-opened app with no file-path argument at all).

- [x] **Second open routes to the existing instance** ✓ — with a caveat worth recording.

  Opening a second `.rehuspike` file via `open` while the app is running never spawned a second
  process — same PID throughout, confirmed via `ps` and by grepping every PID that appeared in
  the unified log for the `Rehuco Spike` process name.

  **But** the log shows this happens *before* `ApplicationSingleton` is even involved: macOS's own
  LaunchServices app-uniquing recognizes the bundle is already running and delivers the second
  file as a **second `QFileOpenEvent` to the same process**, without ever launching a competing
  one. This confirms the existing architecture note (§16.8): *"a bundled `.app` is already kept
  single-instance by the OS ... so the local-server forwarding mainly earns its keep on
  Windows/Linux."*

  To exercise `ApplicationSingleton`'s own `QLocalServer` forwarding path independently (the path
  that *does* matter on Linux, and for any macOS launch that bypasses LaunchServices' uniquing —
  e.g. running the bundle's executable directly rather than through `open`/Finder), the bundle
  executable was invoked a second time directly:

  ```sh
  "build/spike/macos/app/Rehuco Spike.app/Contents/MacOS/Rehuco Spike" /tmp/test2.rehuspike
  ```

  This **did** spawn a second, distinct process — LaunchServices' uniquing only applies to
  LaunchServices-mediated launches (`open`, Finder, Dock) — and that second process's
  `ApplicationSingleton.setup()` correctly detected the primary, forwarded argv over the local
  socket, and exited. The primary's log shows
  `application_singleton: second instance forwarded: ['/tmp/test2.rehuspike']` followed by
  `spike.app: opened: /tmp/test2.rehuspike`. Confirmed working as a fallback, exactly as designed.

  **Observed but out of scope to fix here:** the secondary process's own log shows two benign Qt
  warnings — `QAbstractSocket::waitForBytesWritten() is not allowed in UnconnectedState` — before
  it logs `primary already running ... forwarded argv and exiting`. The forward still succeeds
  (confirmed by the primary receiving it), so this looks like a harmless race in
  `ApplicationSingleton`'s write-then-disconnect teardown sequence, not a functional bug; noted
  for whoever next touches that class, not investigated further here (pre-existing code, unrelated
  to this spike, spike is throwaway by design, `ApplicationSingleton` is kept code with its own
  tests).

## Verdict

**Full success — all three issue #13 acceptance criteria confirmed.**

| Requirement | Approach | Result |
| --- | --- | --- |
| `.app` bundle registered as default opener for `.rehuspike` (UTI + `CFBundleDocumentTypes`) | Briefcase `document_type` config | ✓ |
| Double-click delivers the path via `QFileOpenEvent`, not `argv` | `Application.event()` override (already in `rehuco_agent/app.py`, unchanged) | ✓ |
| Second double-click routes to the existing instance | macOS app-uniquing (primary path) + `ApplicationSingleton`/`QLocalServer` (fallback path) | ✓ |

**Key lessons:**

- **Briefcase's `document_type` config is the whole mechanism** — no hand-written `Info.plist`
  fragment is needed for macOS UTI/`CFBundleDocumentTypes` registration, matching the Windows
  spike's confirmation of Briefcase for that platform's ProgID/AUMID (§1, closed).
- **PySide6's macOS wheels require `min_os_version = "13.0"`** in `[tool.briefcase.app.<name>.macOS]`
  — Briefcase's own default (`11.0`) is too low and the build fails during dependency
  installation with a "no matching distribution" error. Worth carrying into `apps/rehuco-agent`'s
  real Briefcase config when that lands (§16.8, deferred past A0).
  `std-nslog~=2.0.0` (not the older `>=1.0.3` pin used by an earlier Windows-spike commit) is
  the version the current (`v0.4.3`) template pins.
- **`rehuco_agent/app.py`'s existing `QFileOpenEvent` handling needs no changes for macOS** — it
  was already written generically (`isinstance(event, QFileOpenEvent)`), and this spike confirms
  that code path actually fires correctly once the app is a real registered `.app` bundle.
- **All verification was done from the terminal, no GUI/screen-sharing session required** —
  `open <file>` and `lsregister` drive the identical LaunchServices path a Finder double-click
  does, and `log stream`/`log show` observe `QFileOpenEvent` delivery and `ApplicationSingleton`
  forwarding without needing to see a window.
- **macOS's own single-instance app-uniquing (not `ApplicationSingleton`) is what actually
  routes a second Finder double-click** on this platform — confirms, rather than surprises, the
  existing §16.8 note. `ApplicationSingleton`'s `QLocalServer` fallback still works correctly when
  exercised directly (bypassing LaunchServices), which matters for Linux and any non-bundle launch.

## Cleanup

```sh
# Remove the throwaway UTI registration:
LSREG=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
"$LSREG" -u "build/spike/macos/app/Rehuco Spike.app"
```

Then delete `spikes/macos-file-assoc-identity/` per the keep-the-lesson-discard-the-toy pattern.
