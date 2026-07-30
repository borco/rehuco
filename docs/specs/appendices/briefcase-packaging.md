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
(#13, macOS; the Windows half closed in #1) and is meant to **evolve** as production Briefcase
config lands in `packages/rehuco-agent/` and as Windows and Linux packaging are wired up. Where a
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
- **Production Briefcase config in `packages/rehuco-agent/pyproject.toml`** — **landed** (#206), for
  Windows and macOS ([[appendices.briefcase-packaging#briefcase-config]]), driven by the `make agent-dist-build` /
  `agent-dist-package` targets ([[appendices.briefcase-packaging#build-and-iterate]]). **Both halves are built and
  verified**: Windows through a real install, with the association, `.tc` and all three shell verbs landing under one
  identity ([[appendices.briefcase-packaging#windows]]); macOS on Apple silicon through the LaunchServices recipe below
  — UTI claimed, `open` routed, a second open handled in the same instance. `uv tool install` stays the
  developer channel either way ([[packaging-deployment#pypi-publishing]]).
- **Linux packaging** — answered, and the answer is **none of Briefcase's backends**
  ([[packaging-deployment#linux-format]]): Linux ships through `uv tool install` with the desktop entry written by the
  app itself (#209), since that is the whole of Linux integration. What the backends do and
  do not give is in [[appendices.briefcase-packaging#linux-backends]] — notably, none of them registers a file
  association, so Briefcase's `document_type` config is macOS/Windows-only in effect.
- **Code-signing / notarization, auto-update** — not yet done ([[packaging-deployment#auto-update]],
  [[appendices.open-questions#still-open]]).

## 2. The Briefcase config

[[[appendices.briefcase-packaging#briefcase-config]]]

Briefcase reads everything from `pyproject.toml`; no per-OS manifest is hand-maintained —
**and 0.4.4 merges the `[project]` table into its own**, so version (resolved through hatchling even
though it is `dynamic`), description, license, `license-files`, url, author and every `dependencies`
entry are taken from there rather than restated. What `rehuco-agent`'s config adds is only what has
no PEP 621 equivalent — condensed here, with the reasoning in the file's own comments:

```toml
[tool.briefcase]
project_name = "Rehuco"
bundle = "io.github.borco"                 # + the app name -> bundle identifier, macOS UTI, Windows ProgID

[tool.briefcase.app.rehuco-agent]
formal_name = "Rehuco"                     # Rehuco.exe / Rehuco.app, Start-menu entry, install folder
icon = "../../design/icons/rehuco-agent"   # basename only: .ico on Windows, .icns on macOS
sources = ["src/rehuco_agent"]
requires = ["../rehuco-core", "../borco-core", "../borco-pyside"]

[tool.briefcase.app.rehuco-agent.macOS]
requires = ["std-nslog~=2.0.0"]
# PySide6's macOS wheel is macosx_13_0_universal2; Briefcase's 11.0 default is too low (see "Hurdles" below).
min_os_version = "13.0"

# Under macOS, not at app level: on Windows this would add a second, competing ProgID (see below).
[tool.briefcase.app.rehuco-agent.macOS.document_type.rehu]
description = "Rehuco Resource"            # matches the Windows FRIENDLY_NAME the app registers
extension = "rehu"
icon = "../../design/icons/rehuco-agent"   # no dedicated document icon in the design master yet
url = "https://borco.github.io/rehuco/"
mime_type = "application/x-rehuco"         # also what #209's Linux MIME package must register

[tool.briefcase.app.rehuco-agent.windows]
system_installer = false                   # per-user: no UAC, matching the app's own HKCU registration
post_install_script  = "installer/post_install.bat"    # calls Rehuco.exe --register
pre_uninstall_script = "installer/pre_uninstall.bat"   # calls Rehuco.exe --unregister
```

From the `document_type` table Briefcase generates **both** halves of a macOS document-type
declaration, with no hand-edited `Info.plist`:

- `CFBundleDocumentTypes` — so Finder / LaunchServices treat the extension as a document type
  owned by this app, with the right icon.
- `UTExportedTypeDeclarations` — so `mdls`, Spotlight, and any UTI-aware API resolve the extension
  to a concrete Uniform Type Identifier (`<bundle>.<app>.<ext>`, so `io.github.borco.rehuco-agent.rehu`).

Windows gets its own half of the same table — a WiX `ProgId`/`Extension`/`Verb` triple in the MSI,
[[appendices.briefcase-packaging#windows]].

Workspace dependencies need one more line each. They arrive from `[project].dependencies` as bare
names, but Briefcase builds the bundle by pip-installing into it and cannot see the uv workspace, so
each also needs a **direct reference** — a path relative to the app's `pyproject.toml`, which
Briefcase absolutizes. pip then resolves the bare name to that reference, which is what keeps
`rehuco-core` off PyPI (where it is still a `0.0.0` stub) and lets the unpublished `borco-*` resolve
at all:

```toml
# in [tool.briefcase.app.rehuco-agent], alongside the bare names [project].dependencies contributes
requires = ["../rehuco-core", "../borco-core", "../borco-pyside"]
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

**Icons first, and `make icons` builds them** ([[packaging-deployment#design-resources]]): the `.ico` by
downscaling the 1024-px PNG master with ImageMagick, and — **only on macOS** — the `.icns` through `sips`
and `iconutil`, platform tools with no cross-platform equivalent that produces a real multi-resolution
icon set (ImageMagick's ICNS writer emits one resolution, which Finder and the Dock then rescale badly).
Both are gitignored, so a fresh checkout needs that target before any bundle can be built. The Briefcase
targets depend on it, and on `make uis`: Briefcase copies `src/rehuco_agent` verbatim, so the generated
`*_ui.py`/`*_rc.py` must already exist, or the bundle dies on its first import.

**The build sequence — the same on Windows and macOS**, since Briefcase picks the host platform itself:

```sh
# One-time per platform: create + build the bundle. Downloads a Python support package and
# pip-installs the whole Qt stack into it -- minutes, and ~700 MB under packages/rehuco-agent/build/.
make agent-dist-build    # -> build/rehuco-agent/windows/app/src/Rehuco.exe
                         #    build/rehuco-agent/macos/app/Rehuco.app on macOS

# Iterate on app code: re-syncs src/ into the existing bundle, seconds rather than minutes.
make agent-dist-update

# The shippable artifact. Downloads the WiX toolset on first use.
make agent-dist-package  # -> packages/rehuco-agent/dist/Rehuco-<version>.msi
                         #    on macOS a .dmg -- with `BRIEFCASE_ARGS=--adhoc-sign` until signing is filed
make agent-dist-clean    # drop build/ and dist/
```

Each target is one `uv run` around `briefcase`, and the two uv flags in it are both load-bearing:

```sh
uv run --group packaging --directory packages/rehuco-agent --project ../.. briefcase build

# --directory: Briefcase reads the pyproject of the *current* directory, so it must run there.
# --project:   uv must still resolve against the workspace root. Letting it discover the member
#              instead syncs the shared .venv down to that member's own dependencies, evicting
#              pytest/ruff/mkdocs. `packaging` is opt-in, so a later plain `uv sync` prunes it again.
```

Briefcase itself is **not** a workspace dependency of the agent: it lives in the root's opt-in
`packaging` dependency group, so the ~30 packages it drags in (cookiecutter, GitPython, requests,
rich) stay out of a plain `make sync`'s environment.

## 5. Windows: what the MSI registers, and what it does not

[[[appendices.briefcase-packaging#windows]]]

Read off real `make agent-dist-package` runs on 2026-07-28 — Briefcase 0.4.4, WiX 6, the Python 3.14.4
embedded support package, PySide6 6.11.1. The first build produced a 215 MB `dist/Rehuco-0.0.1.msi` from a 699 MB
bundle — of which **437 MB was `PySide6-Addons`**, measured from its own wheel `RECORD`, and nothing
here imports a single module of it. Dropping it (#211) took the very same build to **80.6 MB from a
264 MB bundle** — a 62% cut, and by far the largest change to the artifact in this issue. All that
survives of QtWebEngine is three `.pyi` stubs totalling 96 KB, since Essentials ships type stubs for
the whole API surface; there is not one WebEngine DLL ([[packaging-deployment#channels]]).

**The launcher owns the window's process — the #1 finding, now confirmed on a packaged build.**
`Rehuco.exe` is Briefcase's stub binary with the app's identity stamped into it by `rcedit`:

| PE field | Value | Comes from |
| --- | --- | --- |
| `ProductName`, `FileDescription` | `Rehuco` | `formal_name` |
| `CompanyName` | `Ioan Calin` | `[project].authors[0].name` |
| `ProductVersion`, `FileVersion` | `0.0.1` | the `dynamic` `[project]` version |
| `InternalName` | `rehuco_agent` | the module name |
| icon | `design/icons/rehuco-agent.ico` | `icon` |

Launched, it runs as a process named `Rehuco` that owns its own window — no `python.exe` subprocess —
which is the precondition for the AUMID the app sets at startup to bind to the right HWND
([[packaging-deployment#app-identity]]). One cosmetic gap: `LegalCopyright` still reads the stub's own
`Copyright (C) 2022`, and Briefcase exposes no key for it.

**The installer's chrome is ours, not WiX's.** Left unset, `installer_background` and
`installer_banner` fall through to the WiX Toolset's own red bitmaps — someone else's branding on a
shipped installer, and easy to miss because nothing warns about it. Both are generated by
`make icons` from the same PNG master as the icons: a 493×312 background whose left 164 px (all WiX
leaves uncovered) is the brand slate, and a 493×58 banner. The icon's own rounded square is exactly
that slate, so it dissolves into the strip and only its three bars read. WiX accepts **only** BMP,
with no alpha — hence `BMP3:` and `-alpha remove` in the rule.

**The MSI does not register the file association — it asks the app to.** Declaring `document_type`
here would emit a WiX `ProgId`/`Extension`/`Verb` component under
`Id="io.github.borco.rehuco-agent.rehu"`, and that is a **different identity from the one the app
uses**: `--register` writes `Rehuco.Document` covering `.rehu` *and* `.tc` plus the folder,
folder-background and archive verbs (#43), where the generated component covers `.rehu` alone. Both
are valid registrations of one extension, the later one wins, and the app's own Registry settings
page (#47) — which looks for `Rehuco.Document` — reports **"Not registered" after every MSI install,
forever**, because the two sets never intersect. Observed on the first packaged build, before the
config changed.

So `document_type` is declared under the **macOS** block only (verified: Windows then resolves
`document_type = None`), and the MSI delegates instead — `post_install_script` runs
`Rehuco.exe --register`, `pre_uninstall_script` runs `--unregister` while the exe still exists. One
identity, `.tc` and the shell verbs included, and an uninstall that strands nothing. macOS keeps the
declarative route because it has no `--register` equivalent: only the bundle can claim a UTI.

Two contract details the scripts must respect, both from the generated `.wxs`: the custom actions are
`Return="check"`, so **a non-zero exit rolls the whole install back** — the scripts end in `exit /b 0`
so a failed association can never fail an installation; and they run from `[INSTALLFOLDER]\_installer\`,
so the exe is one directory up. The generated `run_post_install.bat` sets `ALLUSERS`,
`INSTALLER_PATH` and `INSTALLER_UNATTENDED` in the environment and passes **no** arguments.

**Scope.** `system_installer = false` drops WiX's install-scope dialog from the UI flow, leaving the
generated `WixAppFolder = WixPerUserFolder` to stand — so the install is per-user into
`%LOCALAPPDATA%\Programs\<author>\<formal name>\` with no elevation, and the author name becomes a
folder level because WiX uses `Manufacturer` that way. It does **not** narrow the package: the
template hardcodes `Scope="perUserOrMachine"` regardless, so `msiexec ALLUSERS=1` can still install
per-machine. Nothing in the UI offers it.

**The uninstall cleans up, and this was checked on the delegated path itself.** On the first build —
before the scripts existed — the MSI removed its own generated ProgID and left `.rehu` as an empty
key rather than a handler pointing at a deleted `Rehuco.exe` — the failure #206 names. The delegated
path was then verified in its own right on 2026-07-28: uninstalling a build that carries
`pre_uninstall_script` removed **all six** registrations — `Rehuco.Document`, the `.rehu` and `.tc`
defaults, and the folder, folder-background and archive verbs — together with the files, the
Start-menu entry and the ARP row, leaving nothing aimed at the deleted exe.

## 6. Hurdles

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

### A universal2 build needs an x86_64 wheel for *every* dependency

**Symptom:** the arm64 pass installs cleanly, then `Installing binary app requirements for x86_64...
errored` with `No matching distribution found for cbor2==6.1.3` — while that exact version installed
seconds earlier.

**Cause:** Briefcase's default macOS build is universal2, so it installs the dependency set twice,
once per architecture, **pinned to the versions the first pass resolved** so the two halves match.
`cbor2` publishes no x86_64 macOS wheel at 6.x (that platform stops at 5.9.0), so the pin is
unsatisfiable. Any dependency that drops Intel macOS wheels does the same thing.

**Fix:** `universal_build = false` under `[tool.briefcase.app.<name>.macOS]` — the app becomes
Apple-silicon-only. Briefcase's own error message suggests it. The alternative, pinning the app down
to `cbor2` 5.x to suit the packager, gets the dependency direction backwards. Revisit only if Intel
Macs become a target, which would mean holding every dependency to an x86_64-capable version.

### `std-nslog` version tracks the template, not an old pin

`[tool.briefcase.app.<name>.macOS].requires` needs `std-nslog` (Briefcase's macOS stdout/stderr →
unified-log shim). The current Briefcase template (`v0.4.3`) pins `std-nslog~=2.0.0`; an earlier
Windows-spike commit referenced `>=1.0.3`. Use the version the active template expects, or the
build resolver complains.

### Briefcase's `license` selection keys are strict

`briefcase new` (and config validation) expect an SPDX-style key like `MIT`, not a prose string
like `"MIT license"` — the latter fails validation with an "invalid override value" error. Minor,
but wastes a scaffolding round-trip if hit.

## 7. Verification recipe, macOS (terminal-driven, no GUI session)

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

## 8. What the #13 spike confirmed

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

## 9. Linux: what the backends actually do

[[[appendices.briefcase-packaging#linux-backends]]]

Read against **Briefcase 0.4.4** and its published cookiecutter templates on 2026-07-28, because the
format decision ([[packaging-deployment#linux-format]]) turns on facts the feature tables do not
state — and two of them contradict what a reader would assume from the macOS half of this appendix.

| Backend | Exists | Interpreter | Emits a `.rehu` association | Verdict for this app |
| --- | --- | --- | --- | --- |
| `linux system` — `.deb`, `.rpm`, `.pkg.tar.zst` | yes | the target distro's `/usr/bin/python3` | no | usable only where the distro's `python3` is a version the dependency set has wheels for |
| `linux appimage` | yes | bundled | no | ruled out — upstream discourages it and names PySide |
| `linux flatpak` | yes | the Flatpak runtime's (freedesktop SDK 25.08: Python 3.13) | no | ruled out — sandboxed, and its runtime is below the app's floor |
| `linux snap` | **no** | — | — | `briefcase/platforms/linux/snap.py` is one line: `# A Snap implementation would go here!` |

**1. No Linux backend registers a file association.** The `.desktop` file each template generates
carries `Type`/`Name`/`Exec`/`Icon`/`Comment` (plus `StartupWMClass` for system and AppImage) and
**no `MimeType=` line**; none of the three template repositories contains a MIME package `.xml` at
all. So the `document_type` table ([[appendices.briefcase-packaging#briefcase-config]]) — which on
macOS generates both halves of the document-type declaration — produces *nothing* on Linux beyond a
document-type icon. Registering `.rehu` there is the app's own job (#209), whatever the format.

**2. The system backend takes the distro's interpreter, not a bundled one.** `platforms/linux/system.py`
reads the target image's `python3` version, keeps it as `python_version_tag`, refuses a version below
Briefcase's own floor, warns when it differs from the host's, and adds `libpython3.X` to the package's
`Depends:`. The docs state it plainly — "*the app will use the system Python install, and the standard
library provided by the system*", and "*It is therefore necessary to build a different system package
for every distribution you want to target*", with Docker target images as the way to do that. Windows
and macOS bundle a support-package interpreter; **Linux is the exception**, and that single fact is what
makes the per-distro matrix appear.

**3. Which distributions that leaves.** Only one floor applies, and it is **ours**: the agent declares
`requires-python = ">=3.14"`. The Qt stack imposes none of its own — `PySide6` (`cp310-abi3`),
`pyside6-qtads` (`cp310-abi3`) and `pyside6-scintilla` (`cp311-abi3` from 5.6.3.6) all publish
limited-API wheels that any newer CPython accepts, for `manylinux_2_34_x86_64` **and**
`manylinux_2_38_aarch64` — so **both architectures are packageable**, with the aarch64 wheels wanting
glibc ≥ 2.38. A system package is therefore buildable wherever the target's `python3` is 3.14 or newer:

| Target | system `python3` | Buildable |
| --- | --- | --- |
| Ubuntu 26.04 LTS (resolute) | 3.14.3 | yes |
| Ubuntu 24.04 LTS (noble) | 3.12.3 | no |
| Debian 13 (trixie) | 3.13.5 | no |
| freedesktop SDK 25.08 (the Flatpak runtime) | 3.13.x | no |

Versions read from `packages.ubuntu.com` / `packages.debian.org` and, for 24.04, from the machine in
use, on 2026-07-28. Because the floor is the agent's own declaration rather than an upstream limit,
lowering it is a lever this project holds — at the cost of the Python 3.14 semantics the code relies on
([[appendices.code-conventions#python]]).

**AppImage, in upstream's own words** — the warning banner `platforms/linux/appimage.py` prints on every
build: "*Briefcase supports AppImage in a best-effort capacity. It has proven to be highly unreliable as
a distribution platform. AppImages cannot use pre-compiled binary wheels, and has significant problems
with most commonly used GUI toolkits (including GTK and PySide).*" The documentation matches it — "*we
strongly discourage the use of AppImages for distribution*", and "*the core team does not consider
addressing AppImage bugs a priority*". A PySide6 app is the case they are warning about, so the
"universal fallback" AppImage looked like on paper is not one here.

> [!NOTE]
> Flatpak also cannot be built inside Docker or on an NFS-mounted drive (it builds in its own sandbox),
> so it would constrain the release CI host as well as the runtime.

### Building the AppImage without Briefcase

- [#210: feat: build the Linux AppImage for rehuco-agent with python-appimage](https://github.com/borco/rehuco/issues/210)

Since the AppImage *format* is fine and only `linuxdeploy` is not
([[packaging-deployment#linux-format]] point 5), the Linux artifact is built with
[python-appimage](https://github.com/niess/python-appimage) instead: it extracts a relocatable CPython
from a manylinux image and installs wheels into it untouched, so `auditwheel`'s work is never redone.
A recipe is a folder holding `requirements.txt`, a `*.desktop` file and an icon named after its `Icon=`
value; the build must run where the wheels are installable (glibc ≥ 2.34 for x86_64, ≥ 2.38 for
aarch64). **The desktop file must not be named `entrypoint.desktop`** — python-appimage globs
`entrypoint.*` for the *shell script* half of the recipe, and matched the desktop file instead the one
time this repo's own recipe was named that way, silently turning the packaged app's `AppRun` into an
attempt to execute a `.desktop` file as shell (`packages/rehuco-agent/appimage/rehuco-agent.desktop`,
found by actually running the build rather than by reading the upstream source).

**What's built (#210):** `packages/rehuco-agent/appimage/` holds `rehuco-agent.desktop` and
`entrypoint.sh` (checked in); `make agent-appimage-build` copies the icon in from the design master and
generates `requirements.txt` with **absolute paths** to the four workspace packages, in dependency order
(`borco-core`, `rehuco-core`, `borco-pyside`, `rehuco-agent`) — python-appimage `pip install`s each
`requirements.txt` line *separately*, so a bare package name would resolve against PyPI's own unrelated
**0.0.1 stub** releases of the same four names rather than this checkout's code. `rehuco-agent` installing
last then finds the first three already satisfied locally and reaches PyPI only for its real third-party
dependencies (`PySide6-Essentials`, etc.). `python-appimage build app -p 3.14` (a release-tag version,
"3.14" — not the patch version "3.14.6" the resolved runtime turns out to be) auto-selected the more
portable `manylinux2014_x86_64` base over the `manylinux_2_28` this repo's docs otherwise reference,
since python-appimage's own release picks the lowest compatible manylinux tag published for that Python
version; either way the *build host* still needs glibc ≥ 2.34 to install the Qt stack into it.

**A hatchling gap this surfaced, unrelated to the AppImage format itself:** hatchling's default file
selection follows VCS tracking, so `packages/rehuco-agent`'s gitignored `*_ui.py`/`*_rc.py`
(pyside6-uic/-rcc output, `make uis`) were silently dropped from every wheel build — confirmed with a
bare `uv build --package rehuco-agent`, which produced a wheel importing cleanly until the first Qt
resource read, then `ImportError: cannot import name 'main_rc'`. Briefcase never hit this (it copies
`src/rehuco_agent` verbatim, no wheel build) and neither does a plain `uv sync` (an editable install has
no file-selection step) — a real `pip install <path>`, which is exactly what the AppImage recipe's
`requirements.txt` does, was the first thing to actually build a wheel from this package. Fixed by adding
`[tool.hatch.build] artifacts = ["*_ui.py", "*_rc.py"]` to `packages/rehuco-agent/pyproject.toml`, which
force-includes matching files regardless of VCS status — so this was latent in the PyPI-publishable wheel
all along, not something this issue introduced.

What the runtime gives the app, read from `type2-runtime`'s `runtime.c` on 2026-07-28 — these are the
facts the self-registration path (#209) depends on:

| Variable | Meaning |
| --- | --- |
| `APPIMAGE` | absolute path of the `.AppImage` file the user launched — **the only correct `Exec=` target** |
| `APPDIR` | the temporary mount (`/tmp/.mount_XXXXXX`), gone when the process exits |
| `ARGV0` | the name the file was invoked as |
| `OWD` | the working directory the launch happened in |

- **`Exec=` must come from `APPIMAGE`**, never from `sys.executable` or `__file__` — both point inside
  `APPDIR`, which is a mount that disappears, so an entry written from them is dead on the next boot.
- **Own-namespace arguments only.** The runtime intercepts `--appimage-extract`,
  `--appimage-extract-and-run`, `--appimage-mount`, `--appimage-offset`, `--appimage-portable-home`,
  `--appimage-portable-config`, `--appimage-signature`, `--appimage-updateinfo[rmation]`,
  `--appimage-version` and `--appimage-help`, and errors on any *other* `appimage-`-prefixed argument.
  Everything else is forwarded verbatim, so `--register`, `--unregister` and a `.rehu` path arrive as
  normal `argv`.
- **System libraries are not bundled.** Python and the wheels are; Qt's X/Wayland/GL/font dependencies
  are the host's problem, which is the one thing to verify in a bare container before calling the
  artifact "download and run".
