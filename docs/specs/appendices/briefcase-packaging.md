# Briefcase Packaging — Native App Builds, File Association, and App Identity

[[[appendices.briefcase-packaging]]]

## Overview

[[[appendices.briefcase-packaging#overview]]]

How rehuco uses [Briefcase](https://briefcase.readthedocs.io/) to build `rehuco-agent` into a
native, double-clickable application with OS-registered file association and app identity — the
*how-to and the hurdles*, complementing [[packaging-deployment#app-identity]] (which records the *decision* to use
Briefcase over
PyInstaller and *why*).

This appendix starts from the macOS half of the file-association spike
([#13](https://github.com/borco/rehuco/issues/13), macOS; the Windows half closed in
[#1](https://github.com/borco/rehuco/issues/1)) and is meant to **evolve** as production Briefcase
config lands in `apps/rehuco-agent/` and as Windows and Linux packaging are wired up. Where a
detail is still spike-proven rather than production-shipped, it says so.

## 1. Status

[[[appendices.briefcase-packaging#status]]]

- **macOS file association + `QFileOpenEvent` delivery + single-instance routing** — proven end to
  end on current versions by the #13 spike ([[appendices.briefcase-packaging#verification]]). The `rehuco-agent` app
  code it depends on
  (`Application.event()`'s `QFileOpenEvent` branch, `ApplicationSingleton`) already exists and
  needs no macOS-specific changes.
- **Windows ProgID / AUMID default-handler + taskbar identity** — proven by #1; the dev-time story
  and its hurdles live in [[appendices.windows-dev-launcher#overview]] (the C launcher). Briefcase is the confirmed
  end-user packager
  there too.
- **Production Briefcase config in `apps/rehuco-agent/pyproject.toml`** — **not yet landed.** It is
  wider-distribution polish, deferred past the personal critical path ([[packaging-deployment#app-identity]], plan:
  deferred).
  `uv tool install` covers the author's own machines until then.
- **Linux packaging, code-signing / notarization, auto-update** — not yet done ([[packaging-deployment#auto-update]],
  [[appendices.open-questions#still-open]]).

## 2. The Briefcase config

[[[appendices.briefcase-packaging#briefcase-config]]]

Briefcase reads everything from `pyproject.toml`; no per-OS manifest is hand-maintained. The
config below is what the #13 spike used and verified; the production version in `rehuco-agent`
will differ only in names (`spike` → `rehuco-agent`, `.rehuspike` → `.rehu`, throwaway bundle ID →
production bundle ID).

```toml
[tool.briefcase.app.spike.document_type.rehuspike]
description = "Rehuco Spike File"
extension = "rehuspike"
icon = "rehuco-spike"
url = "https://github.com/borco/rehuco"
mime_type = "application/x-rehuco-spike"

[tool.briefcase.app.spike.macOS]
requires = ["std-nslog~=2.0.0"]
# PySide6's macOS wheel is macosx_13_0_universal2; Briefcase's 11.0 default is too low (see "Hurdles" below).
min_os_version = "13.0"
```

From the `document_type` table Briefcase generates **both** halves of a macOS document-type
declaration, with no hand-edited `Info.plist`:

- `CFBundleDocumentTypes` — so Finder / LaunchServices treat the extension as a document type
  owned by this app, with the right icon.
- `UTExportedTypeDeclarations` — so `mdls`, Spotlight, and any UTI-aware API resolve the extension
  to a concrete Uniform Type Identifier (`com.<bundle>.<app>.<ext>`).

Local (not-yet-on-PyPI) workspace dependencies go into `requires` as **relative paths**, since
Briefcase builds the bundle by pip-installing into it and cannot see the uv workspace:

```toml
requires = ["PySide6>=6.9", "../../packages/borco-core", "../../packages/borco-pyside"]
```

## 3. The app-side wiring it relies on

[[[appendices.briefcase-packaging#app-side-wiring]]]

Briefcase only produces the bundle and its registration; the app must still handle the two macOS
delivery mechanics. Both already exist in `rehuco-agent` and needed no change for macOS.

macOS does **not** pass a double-clicked path as `argv` — it arrives as a Cocoa-originated
`QFileOpenEvent`:

```python
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

class Application(QApplication):
    def event(self, event: QEvent) -> bool:
        if isinstance(event, QFileOpenEvent):
            self.open_path(event.file())
            return True
        return super().event(event)
```

`main()` still also reads `sys.argv[1:]`, for parity with Windows' `argv`-based forwarding ([[nodes#single-instance]])
and for `python -m ... <path>` during development.

Single-instance routing uses the same `QLocalServer`/`QLocalSocket` mechanism as every platform
([[nodes#single-instance]]) — no macOS-specific code. See [[appendices.briefcase-packaging#verification]] for *when*
this path actually fires on macOS (it is a
fallback there, not the primary route).

```python
from borco_pyside.core.application_singleton import ApplicationSingleton

app = Application(sys.argv)
singleton = ApplicationSingleton()
if not singleton.setup(APP_ID):   # False -> forwarded argv to the existing primary; exit
    sys.exit(0)
singleton.other_instance_run.connect(open_forwarded)
```

## 4. Build and iterate

[[[appendices.briefcase-packaging#build-and-iterate]]]

**Icon first.** Briefcase's `icon = "rehuco-spike"` config points at a basename; on macOS it needs
a matching `.icns` next to `pyproject.toml`. macOS builds one from the `.svg` master with the
platform tools (no third-party dependency). This is **not yet a Makefile target** — the Windows
`.ico` rule already lives in the Makefile (`%.ico: %.svg` via `magick`); the `.icns` equivalent
below should be wired in the same way when production packaging lands ([[packaging-deployment#app-identity]]), rather
than run by
hand:

```sh
magick -background none logo.svg -resize 1024x1024 rehuco-spike-1024.png
mkdir icon.iconset
for size in 16 32 64 128 256 512; do
  sips -z $size $size rehuco-spike-1024.png --out "icon.iconset/icon_${size}x${size}.png"
  double=$((size * 2))
  sips -z $double $double rehuco-spike-1024.png --out "icon.iconset/icon_${size}x${size}@2x.png"
done
iconutil -c icns icon.iconset -o rehuco-spike.icns
rm -rf icon.iconset rehuco-spike-1024.png
```

**Then build:**

```sh
# One-time: build the .app (downloads Python + PySide6 into the bundle; a few minutes).
briefcase build macOS
# Output: build/<app>/macos/app/<Formal Name>.app

# Iterate on app code (fast; re-syncs src/ into the existing bundle, seconds):
briefcase update macOS
```

The spike ran this against a throwaway local venv (`uv venv`, then `uv pip install` of PySide6,
the two `borco-*` editable packages, the app itself, and `briefcase`). In production this becomes
a Makefile target against the workspace venv.

## 5. Hurdles

[[[appendices.briefcase-packaging#hurdles]]]

Recorded in the order they bite when building a Briefcase macOS bundle for a PySide6 app.

### `min_os_version` must be ≥ the PySide6 wheel's floor

**Symptom:** `briefcase build macOS` fails during dependency install with
`No matching distribution found for PySide6>=6.9` / `Could not find a version that satisfies the
requirement PySide6`, even though PySide6 installs fine into a normal venv.

**Cause:** PySide6's macOS wheel is tagged `macosx_13_0_universal2`. Briefcase pins the bundle's
minimum macOS to its own default (`11.0`) and asks pip for a wheel compatible with *that* floor —
no `13.0`-tagged wheel qualifies, so pip reports "no matching distribution."

**Fix:** set `min_os_version = "13.0"` under `[tool.briefcase.app.<name>.macOS]`. Carry this into
`rehuco-agent`'s production config; revisit only if PySide6 lowers its wheel floor.

### `std-nslog` version tracks the template, not an old pin

`[tool.briefcase.app.<name>.macOS].requires` needs `std-nslog` (Briefcase's macOS stdout/stderr →
unified-log shim). The current Briefcase template (`v0.4.3`) pins `std-nslog~=2.0.0`; an earlier
Windows-spike commit referenced `>=1.0.3`. Use the version the active template expects, or the
build resolver complains.

### Briefcase's `license` selection keys are strict

`briefcase new` (and config validation) expect an SPDX-style key like `MIT`, not a prose string
like `"MIT license"` — the latter fails validation with an "invalid override value" error. Minor,
but wastes a scaffolding round-trip if hit.

## 6. Verification recipe (terminal-driven, no GUI session)

[[[appendices.briefcase-packaging#verification]]]

`open` and `lsregister` drive the *exact same* LaunchServices path Finder uses for a double-click,
so the whole flow is verifiable over SSH with no screen attached — how the #13 spike was checked.

```sh
# Register the built .app with LaunchServices (Finder does this automatically on first copy/launch):
LSREG=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
"$LSREG" -f "build/<app>/macos/app/<Formal Name>.app"

# Confirm the UTI is claimed and our .app is the Owner:
"$LSREG" -dump | grep -A6 "com.<bundle>.<app>.<ext>"

# Confirm a fresh file resolves to our UTI:
echo test > /tmp/test.<ext>
mdls -name kMDItemContentType /tmp/test.<ext>   # -> com.<bundle>.<app>.<ext>

# Open it exactly like a Finder double-click would (extension alone, no -a):
open /tmp/test.<ext>

# Watch QFileOpenEvent delivery and single-instance routing live:
log stream --style compact --predicate 'process == "<Formal Name>"'

# Clean up the throwaway registration when done:
"$LSREG" -u "build/<app>/macos/app/<Formal Name>.app"
```

## 7. What the #13 spike confirmed

[[[appendices.briefcase-packaging#spike-confirmed]]]

Tested on Python 3.14.6, PySide6 6.11.1, Briefcase 0.4.3, macOS 26.5.1 (2026-07-02). All three of
the spike's acceptance criteria passed:

| Requirement | Mechanism | Result |
| --- | --- | --- |
| `.app` registered as default opener for the extension (UTI + `CFBundleDocumentTypes`) | Briefcase `document_type` config | ✓ |
| Double-click delivers the path via `QFileOpenEvent`, not `argv` | `Application.event()` override (already in `rehuco_agent/app.py`) | ✓ |
| Second double-click routes to the existing instance | macOS app-uniquing (primary) + `ApplicationSingleton`/`QLocalServer` (fallback) | ✓ |

Two behaviours are worth keeping in mind for the production wiring:

- **macOS's own app-uniquing — not `ApplicationSingleton` — routes a second Finder double-click.**
  LaunchServices sees the bundle is already running and delivers the second file as another
  `QFileOpenEvent` to the same process, without launching a competitor. This *confirms* the [[packaging-deployment#app-identity]]
  note that "a bundled `.app` is already kept single-instance by the OS, so the local-server
  forwarding mainly earns its keep on Windows/Linux." `ApplicationSingleton`'s `QLocalServer`
  fallback still works when exercised directly (invoking the bundle executable, bypassing
  LaunchServices) — which is exactly the path that matters on Linux and for non-LaunchServices
  launches.
- **A benign teardown warning on the forwarding path.** When the `QLocalServer` fallback *does*
  fire, the exiting secondary logs two `QAbstractSocket::waitForBytesWritten() is not allowed in
  UnconnectedState` warnings before `primary already running ... forwarded argv and exiting`. The
  forward still succeeds (the primary receives the path), so this is a harmless race in
  `ApplicationSingleton`'s write-then-disconnect teardown, not a functional bug — noted for
  whoever next touches that (kept, tested) class.
