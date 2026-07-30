# §16. Code Organization, Packaging, and Deployment

[[[packaging-deployment]]]

## Overview

[[[packaging-deployment#overview]]]

A monorepo with **uv workspaces** is the chosen structure, driven by three concrete pains: refactoring code between the
shared library and the apps (currently a multi-repo/submodule dance of coupled commits), tooling confusion over *which*
`.venv` is active (a multi-root VSCode layout has one venv per root, and tools — including AI coding assistants — guess
wrong), and independent PyPI publishing of the shared libraries.

## §16.1 Why uv workspaces

[[[packaging-deployment#uv-workspaces]]]

- **One shared `.venv` at the workspace root**, containing every member as an editable install. This eliminates the
  "which venv?" ambiguity at its source: there is exactly one environment, every package is always importable from it,
  nothing to guess. (This is the strongest single reason for the move.)
- **Atomic cross-package refactors.** Moving a widget from an app into the shared library becomes one commit in one
  repo, instead of a commit in the submodule plus a pointer-bump commit in the consumer.
- **Single lockfile, consistent versions** across members — which for a set of sibling PySide6 apps sharing a library is
  a benefit (it forces version compatibility), not a limitation.

The one real constraint workspaces impose: all members resolve against **one dependency set**, so two members needing
conflicting versions of the same package would fail to resolve. For this project (all the author's own apps over a
shared Qt-era stack) that's acceptable and even desirable.

## §16.2 Three packages, mapping onto the node/agent/shared-library split

[[[packaging-deployment#three-packages]]]

- [#12: Add borco-core and borco-pyside generic packages; move ApplicationSingleton to borco-pyside](https://github.com/borco/rehuco/issues/12)

The packaging boundary mirrors the architecture's node/agent split ([[nodes#two-roles]]):

```txt
rehuco/                   # monorepo root
  .venv/                  # the one shared environment (development only)
  packages/
    borco-core/           # generic, non-rehuco utilities (no GUI dep) — temporary guest, moving out
    borco-pyside/         # generic, non-rehuco PySide widgets/utilities — temporary guest, moving out
    rehuco-agent/         # desktop GUI: depends on rehuco-core + PySide6/scintilla/ads
    rehuco-core/          # shared library: .rehu model, plugin identity, migrations — PUBLISHABLE
    rehuco-node/          # headless service: depends on rehuco-core + FastAPI/uvicorn/zeroconf
  pyproject.toml          # virtual workspace root: [tool.uv.workspace] only, no [project]
  uv.lock                 # single lockfile
```

The **virtual workspace root** (no `[project]` table, only `[tool.uv.workspace]`) is a pure organizational container —
it can't itself be published and holds no app code, keeping the root clean. Shared libraries are publishable leaf
packages (they depend only on PyPI packages, never on the apps, so they carry no workspace-internal dependencies that
would block publishing).

The `borco-*` packages (`borco-core`, `borco-pyside`) are **generic, non-rehuco** utilities under the author's own
`borco` namespace — a home for reusable code with no rehuco coupling. They are **temporary guests** in this monorepo,
hosted here only while their APIs settle, and are **scheduled to move to their own repository** (or a separate generic
monorepo) later; nothing rehuco should assume they stay here. `borco-core` is GUI-free; `borco-pyside` carries the
Qt-dependent pieces and depends on `borco-core`. Together they are the successor of the earlier planned generic PySide
package and of the old standalone PySide utility library. The first piece to land is
`borco_pyside.core.ApplicationSingleton` — the single-instance guard consumed by `rehuco-agent`
([[packaging-deployment#three-packages]] tree).

## §16.3 PyPI publishing and `uv tool install`

[[[packaging-deployment#pypi-publishing]]]

- Each member has its own `pyproject.toml` (name, version, build backend) and **publishes to PyPI independently** —
  a `<package>-X.Y.Z` tag push builds and publishes exactly the package it names, and nothing else. The monorepo
  structure is invisible to PyPI; it just sees a normal wheel.
- **A tag is the only way to publish, and this document deliberately describes no other.** There is no local
  build-and-upload path, and no command here to copy: a hand-run upload publishes an unreviewed working tree over a
  long-lived token, and a PyPI release cannot be withdrawn once it exists. The steps that actually run are
  `.github/workflows/publish-packages.yml` — read the workflow, which is the only place they are written down. Why
  it is shaped that way is [[appendices.continuous-integration#publish-packages]]; how to cut a release is
  [[appendices.release-runbook#cut-the-release]].
- The node and agent are installable as tools: **`uv tool install rehuco-node`** (ideal — headless service, console
  entry point) and **`uv tool install rehuco-agent`** (works for the GUI; native installers / file-association
  registration are a later polish for wider distribution ([[packaging-deployment#app-identity]]), not needed for the
  author's own machines).
- **Three packages, not one-package-with-extras.** Extras were considered (`rehuco[node]` / `rehuco[app]`) but rejected:
  extras are *additive and cannot subtract a base dependency*, so any GUI dependency reachable from the base would still
  be pulled by `rehuco[node]` — adding unwanted GUI overhead to a headless service. Separate packages make "the node has
  no GUI dependencies" **structural rather than carefully-maintained**, and let each package carry its own
  `requires-python` floor.

## §16.4 The TS-230 as NAS: SMB mount, not a node host

[[[packaging-deployment#ts230-as-nas]]]

The QNAP TS-230 is used as a **NAS**, not as a compute host. It serves its storage over the existing Samba (SMB) share.
`rehuco-node` runs on capable hardware (Mac mini, always-on Linux box) and accesses TS-230 content via that SMB mount —
treating it as a local path. No node needs to run on the TS-230 itself, and the glibc constraint
([[packaging-deployment#glibc-canary]]) plays no role in deployment.

This is already an option the architecture anticipated ([[mounts-and-storage#rehuco-scope]]): the box owning the disks
doesn't need to run its own node if another always-on machine covers the serving role via a mount. Choosing it as the
default simplifies deployment significantly. Because the always-on node keeps running while the TS-230 may be powered
off for long stretches, the node must tolerate the mount being offline without blocking — see
[[mounts-and-storage#offline-mounts]].

**Atomic-save invariant over SMB ([[data-model#write-integrity]]):** an SMB `rename` is a server-side operation — the
server executes it locally; no data crosses the network. The temp file must be written into the same directory as the
target so that source and destination are on the same server-side filesystem. With that constraint, the
write-temp-then-rename pattern is correct and cheap over SMB.

**The monorepo workspace remains the development environment only** — it is never synced to a remote host. Deployment
installs individual published packages: `uv tool install rehuco-node` on any capable box, `uv tool install rehuco-agent`
on GUI machines.

## §16.5 TS-230 glibc canary — historical findings

[[[packaging-deployment#glibc-canary]]]

Since the node does not run on the TS-230 ([[packaging-deployment#ts230-as-nas]]), the glibc canary is **not an active
requirement**. The findings below are kept as a reference in case direct QNAP deployment is ever reconsidered.

The initial canary confirmed that all planned node dependencies install and import successfully on glibc 2.23 / aarch64
— so the QNAP-as-node option remains technically viable. The automated CI canary ([[packaging-deployment#auto-canary]])
has been **suspended** as it guards a deployment model that is no longer in use.

> [!NOTE]
> **rehuco-node dependencies**
>
> | Package | TS-230 version | Canary version |
> | --- | --- | --- |
> | annotated-doc | 0.0.4 | 0.0.4 |
> | annotated-types | 0.7.0 | 0.7.0 |
> | anyio | 4.14.1 | 4.14.1 |
> | cffi | 2.0.0 | 2.0.0 |
> | click | 8.4.2 | 8.4.2 |
> | cryptography | 49.0.0 | 49.0.0 |
> | fastapi | 0.138.2 | 0.138.2 |
> | h11 | 0.16.0 | 0.16.0 |
> | httptools | — | 0.8.0 |
> | idna | 3.18 | 3.18 |
> | ifaddr | 0.2.0 | 0.2.0 |
> | pycparser | 3.0 | 3.0 |
> | pydantic | 2.13.4 | 2.13.4 |
> | pydantic-core | 2.46.4 | 2.46.4 |
> | python-dotenv | — | 1.2.2 |
> | pyyaml | — | 6.0.3 |
> | starlette | 1.3.1 | 1.3.1 |
> | typing-extensions | 4.15.0 | 4.15.0 |
> | typing-inspection | 0.4.2 | 0.4.2 |
> | uvicorn | 0.49.0 | 0.49.0 |
> | uvloop | — | 0.22.1 |
> | watchfiles | — | 1.2.0 |
> | websockets | — | 16.0 |
> | zeroconf | 0.150.0 | 0.150.0 |
>
> *Recorded on: 2026-06-30*

### §16.5.1 Initial canary result (2026-06-30)

[[[packaging-deployment#initial-canary]]]

- [#5: spike: QNAP/glibc dependency canary](https://github.com/borco/rehuco/issues/5)

Tested on the physical TS-230: glibc 2.23, aarch64, Python 3.14.6 (uv-managed).
All target packages installed from PyPI wheels (`manylinux2014_aarch64`) and imported successfully.

> [!WARNING]
> **Always export `TMPDIR` before running the uv installer on the TS-230.** `/tmp` is a 64 MB RAM disk shared
> with system processes; exhausting it causes system errors and stops the RAM disk — a reboot is required to
> recover. Set up a persistent tmp first:
>
> ```bash
> mkdir -p ~/tmp
> export TMPDIR=~/tmp
> curl -LsSf https://astral.sh/uv/install.sh | sh
> ```
>
> Normal `uv` operation (venv creation, package install) does not need `TMPDIR`.

**Conclusion:** no glibc constraint on any of the node's planned dependencies at current versions.
Cold-import time on TS-230 ARM hardware is ~3.3 s — expected, not a compatibility issue.

### §16.5.2 Automated canary: three-tier verification

[[[packaging-deployment#auto-canary]]]

- [#9: feat: container canary + CI workflow for node glibc compatibility](https://github.com/borco/rehuco/issues/9)

The canary runs at three tiers, ordered fastest → most authoritative:

1. **Local / Mac mini** — native aarch64, no QEMU overhead. Run `ci/node-canary.sh` inside the container
   locally (`--platform linux/arm64` is a no-op on M-series hardware). Fast feedback when bumping dependencies.
2. **GitHub Actions** — QEMU emulation of aarch64 on an x86_64 runner (`.github/workflows/node-canary.yml`).
   Triggers on push to canary-related files and on a weekly schedule. Keeps the compatibility promise
   continuously verified without manual effort.
3. **Physical TS-230 (`ssh nas`)** — ground-truth on real glibc 2.23 hardware. On-demand only; see [[packaging-deployment#initial-canary]]
   for initial run notes and the `TMPDIR` warning.

`ci/node-canary.sh` installs rehuco-node's direct PyPI dependencies inside
`quay.io/pypa/manylinux2014_aarch64` (glibc 2.17 floor, more conservative than the TS-230's 2.23) and
smoke-imports each one. A missing `manylinux2014_aarch64` wheel or a glibc-version mismatch exits non-zero.

## §16.6 Migrating existing repos

[[[packaging-deployment#migrating-repos]]]

**Decided: start the monorepo fresh.** Per-repo git history of the old apps isn't valued enough to preserve (the author
is comfortable starting clean — "what's another repo"). The old rehuco-predecessor repos (`resource-hub`, `tutcatalog5`,
`tutcatalog4`) are not grafted in. This avoids the `git subtree`/`git-filter-repo` fiddliness entirely. The generic
PySide utilities that used to live in a standalone package are likewise reintroduced fresh as the `borco-*` packages
([[packaging-deployment#three-packages]]) rather than grafted in — no old clone or remote needs to survive.

## §16.7 Dependency licensing policy

[[[packaging-deployment#licensing-policy]]]

**Principle: the choice of the final application's license must stay with the author, not be forced by a dependency.**
GPL is fine *by deliberate choice* for a final app; being *compelled* into GPL by a linked library is not acceptable —
it removes the author's freedom and entangles the reusable libraries (`rehuco-core`, `pyside_ibo`, etc.) that are meant
to be independently publishable under whatever license the author picks. (This principle is already evidenced by the
author writing an MIT-licensed `pyside6-scintilla` rather than depending on a copyleft alternative.)

Concrete consequence for **docking**:

- **Use `pyqtads` (Qt-Advanced-Docking-System), not KDDockWidgets.** Both are mature and feature-comparable
  (detach/float/nest/auto-hide/delete-on-close), and KDDockWidgets is in some respects the more capable *framework*
  (KDAB pedigree, native QML docks, deeper customization). But:
  - **KDDockWidgets is GPL 2.0/3.0** (or paid commercial). Linking it makes the *entire agent* a GPL combined work —
    cascading into the publish plan ([[packaging-deployment#pypi-publishing]]) and risking entanglement of the reusable
    libraries. This is a property of the license, not something the binding/packaging can engineer around.
  - **`pyqtads` is permissively licensed (LGPL)** — it can be linked from an app of any license without forcing the
    app's license — **and ships prebuilt PySide6/PyQt6/PyQt5 bindings on PyPI**, so it drops into the uv workspace as a
    normal dependency with no build step.
- The packaging objection to KDDockWidgets (no PyPI wheel; bindings must be built from source via
  shiboken+CMake+libclang) is one the author *could* solve — the same CI-built-binding work already done for
  `pyside6-scintilla` (shiboken) and `lexilla` (nanobind). So bindings are **not** the blocker. **The license is the
  blocker**, and it is not solvable by effort.
- KDDockWidgets is therefore foreclosed for this project. The QML-in-`pyqtads` approach (QQuickWidget hosted in a widget
  dock) was **re-verified on current versions** by spike #4 ([[packaging-deployment#qml-regression]]) and holds; the
  fallback — constraining how QML is used (non-detachable docks, reduced QML footprint) — is held in reserve, **not**
  needed, and switching to KDDockWidgets stays foreclosed regardless.

### §16.7.1 QML-in-`pyqtads` regression check (spike #4)

[[[packaging-deployment#qml-regression]]]

- [#4: spike: pyqtads + QML integration regression check](https://github.com/borco/rehuco/issues/4)

Spike #4 re-verified the QML-in-`pyqtads` approach on **PySide6 6.11.1 + pyside6-qtads 5.0.0** (a
major bump from `resource-hub`'s 4.5.0.4). All three parts hold:

- **Detach/re-dock** — a `QQuickWidget` dock detaches to a floating window and re-docks with no
  rendering glitches; the injected context object stays live across the cycle (both Python→QML
  property reads and QML→Python slot calls keep working before, during, and after the undock).
- **Coexistence** — a QML dock and QWidget docks share one `CDockManager` layout.
- **Layout save/restore** — `saveState()`/`restoreState()` round-trips the layout blob.

**One caveat to carry forward:** the layout blob does **not** restore a *closed* dock's size —
QtAds reopens it at a minimal size. Whichever slice introduces the dock manager must stash the
containing splitter's sizes on `closeRequested` (`CDockManager.splitterSizes(area)`, keyed by
dock object name) and re-apply them via `setSplitterSizes(area, sizes)` on `viewToggled(True)`.

The dock manager becomes load-bearing once a resource *browser* exists alongside the viewer
([[plugins#browsers]]'s "clicking a resource opens its viewer dock") — a multi-pane shell, not a single-window
form. The three-line wiring snippet and the closed-dock-size workaround stay in
`spikes/pyqtads-qml/` as a working reference until that slice consumes them (then the spike is
deleted and this issue closed).

## §16.8 Desktop distribution, file association, and app identity

[[[packaging-deployment#app-identity]]]

- [#206: feat: Briefcase desktop build — installers with native app identity and file
  association](https://github.com/borco/rehuco/issues/206)
- [#209: feat: Linux desktop integration page — register the .rehu association from the app, like the
  Windows one](https://github.com/borco/rehuco/issues/209)

Distribution splits by audience, structurally (as the package split does, [[packaging-deployment#three-packages]]):

- **`rehuco-core` and `rehuco-node` are pure PyPI** ([[packaging-deployment#pypi-publishing]]) — a library and a
  headless service; no GUI identity, no file association.
- **`rehuco-agent` is dual-channel.** `uv tool install` suffices for the author's own machines and developers
  ([[packaging-deployment#pypi-publishing]]); wider end-user distribution additionally needs a **native app identity** —
  icon, file association, taskbar pin/running indicator, an installer — that a bare install cannot provide.

Two design facts shape the choice:

- **File association is OS-specific, and macOS is the binding constraint.** Only a real application bundle can be a
  document type's default handler there, and the opened path is delivered as an in-process event rather than a
  command-line argument — so it must reach the already-running single instance ([[nodes#single-instance]]). Windows
  registers the association declaratively and needs no elevation. **Linux registers nothing declaratively** — no
  Briefcase Linux backend emits a MIME type at all ([[appendices.briefcase-packaging#linux-backends]]), so there the
  app has to register itself (#209), whichever format it ships in ([[packaging-deployment#linux-format]]).
- **Windows app identity (icon / pin / running) is an identity-registration concern, not a "must be a compiled binary"
  one.** A prior version (`resource-hub`) achieved a correct taskbar icon/pin/running indicator only from a frozen
  PyInstaller build, but the real requirement is a stable per-application identity plus an *in-process* per-app launcher
  — available without freezing. (A plain `uv`/pip entry-point stub is **not** sufficient on Windows: it spawns
  `python.exe` as a subprocess, so the taskbar/pinned identity resolves to Python — the launcher must own the window's
  process, via Briefcase's exe or the dev C launcher, [[appendices.windows-dev-launcher#overview]]. Verified in #1.)
  Freezing the app into a single binary is therefore **not** required.
- **File-manager right-click integration ("open this folder/archive in Rehuco", #43) is Windows-only so far** —
  HKCU shell verbs under `Directory`, `Directory\Background`, and `SystemFileAssociations\<ext>`. macOS (Finder Quick
  Actions/Services, or an Automator-generated workflow) and Linux (no single cross-desktop-environment API — Nautilus
  scripts, Dolphin service menus, etc. are each their own mechanism) equivalents are **not yet implemented**. Revisit
  when distribution expands past the author's own Windows machine, rather than letting this quietly stay Windows-only.

**Decision: package end-user builds with Briefcase, not PyInstaller.** Briefcase does not freeze — it pairs a thin
launcher with an embedded interpreter and the app's source, and declares icon, identity, file association, and installer
from `pyproject.toml`, so the OS-specific registration is generated rather than hand-maintained. The deciding reasons
are **reduced fragility and declarative app identity**, not build speed. MSIX is a possible later upgrade for the
strongest Windows identity. This is wider-distribution polish — not needed for LocalEdit1 or the author's own machines — and the
file-association and single-instance mechanics it rests on were de-risked by a dedicated spike before LocalEdit1 relied on
"double-click opens" (macOS #13, Windows #1). **The how-to and hurdles of actually using Briefcase — config,
build/iterate loop, the macOS UTI/`QFileOpenEvent` recipe, and per-OS gotchas — live in
[[appendices.briefcase-packaging#overview]].** The Linux half of the question — *which package format* — is settled
separately in [[packaging-deployment#linux-format]].

**What that decision now ships (#206):** `rehuco-agent`'s `pyproject.toml` carries the Briefcase config, and
`make agent-dist-build` / `make agent-dist-package` build the bundle and the installer on whichever of the two platforms they
run. The Windows MSI is built and its app identity confirmed on a packaged binary rather than the dev launcher
([[appendices.briefcase-packaging#windows]]); the macOS config carries #13's proven values but has not been rebuilt
since the spike. One thing that decision did not anticipate: the MSI's generated ProgID and the app's own
`Rehuco.Document` are **two registrations of the same extension**, and only one can be Explorer's default — the
overlap and what it costs are in [[appendices.briefcase-packaging#windows]].

### §16.8.1 Two Linux channels: `uv tool install` and an AppImage, both self-registering

[[[packaging-deployment#linux-format]]]

- [#207: decision: Linux distribution format for rehuco-agent — system packages (.deb/.rpm), AppImage, Flatpak
  and/or Snap](https://github.com/borco/rehuco/issues/207)
- [#210: feat: build the Linux AppImage for rehuco-agent with python-appimage](https://github.com/borco/rehuco/issues/210)
- [#208: feat: release CI — build the rehuco-agent installers for Windows, macOS and
  Linux](https://github.com/borco/rehuco/issues/208)

The question was *which package format*, and the answer is **neither a distro package nor a sandbox**: Linux ships
`uv tool install` for anyone with uv, and a **single-file AppImage** for everyone else. Every reason Windows and macOS
require a bundled artifact turns out to be absent here, and Linux's entire integration surface is a handful of text
files the app can write itself. The sandbox axis still decides the sandboxed candidates, and Briefcase's Linux backends
turn out to buy nothing ([[appendices.briefcase-packaging#linux-backends]], Briefcase 0.4.4).

**Decided:**

1. **Sandbox-free — Flatpak and Snap are out, permanently.** Both mediate filesystem access, and this app fails at its
   one job if it cannot read a catalog on an SMB mount ([[mounts-and-storage#offline-mounts]]) or if a file-manager
   launch lands outside the running instance's `QLocalServer` ([[nodes#single-instance]]). Each also has an independent
   disqualifier: **Snap has no Briefcase backend at all** (its module is a one-line placeholder), and Flatpak's
   freedesktop 25.08 runtime provides Python 3.13, below the agent's `>=3.14` floor. The portal behaviour itself was
   **not** tested hands-on — there is no Linux desktop here to test on — but each candidate is refused by a verified
   fact of its own, so the untested risk never has to carry the decision.
2. **Briefcase's AppImage backend is out** — the format is fine, the bundler is not. `linuxdeploy` re-processes
   libraries that `auditwheel` already relocated inside every manylinux wheel, which upstream says "can result in a
   binary library that cannot be loaded at runtime"; hence its own warning that
   AppImages "cannot use pre-compiled binary wheels" and have "significant problems with most commonly used GUI toolkits
   (including GTK and **PySide**)", and that they do not treat AppImage bugs as a priority. A PySide6 app is precisely
   the case being warned about. A hand-rolled AppImage over python-appimage's relocatable runtime never runs
   `linuxdeploy` and so avoids this entirely — which is the route point 5 takes.
3. **The primary channel is PyPI: `uv tool install rehuco-agent`, with the desktop entry written by the app (#209).**
   What Windows needs a bundled launcher *for* does not exist on Linux. There, the whole of desktop integration is a
   `.desktop` entry (`Exec`, `Icon`, `MimeType`, `StartupWMClass`), a MIME package XML, and an icon in the hicolor
   theme, then the two `update-*-database` calls — per-user, no root, and exactly what a `.deb` would install into
   `/usr/share` instead of `~/.local/share`. **Identity works out too, for a reason specific to POSIX:** on Windows a
   console-script shim is an `.exe` that spawns `python.exe`, so the taskbar identity resolves to Python (#1), whereas
   a POSIX shim is a shebang script the kernel execs the interpreter *as* — one process, and the window is the app's
   own. Its name then comes from the entry: `StartupWMClass` matched against WM_CLASS on X11, and the Wayland `app_id`
   from `QGuiApplication.setDesktopFileName()`, which the agent does not call yet (it sets only the window icon) and
   which belongs with #209. And because uv brings its own 3.14, the distro's `python3` stops mattering at all — which
   is what dissolves the per-release matrix that made system packages expensive. `uv tool upgrade` is the update path,
   `uvx rehuco-agent` covers a one-off trial, and the entry's `Exec=` points at the installed shim rather than at
   `uvx`, so a double-click never resolves a version or touches the network.
4. **`.deb` and `.rpm` are not planned.** They would install the same three files the app can write, and charge for it:
   a build per family (`.deb` reaches the Debian side only, `.rpm` has its own macro and dependency conventions), and
   no upgrade path from GitHub — **GitHub Packages has no apt or yum registry** ([[packaging-deployment#channels]]),
   so a real repository means GitHub Pages plus `reprepro`/`aptly` and a signing key owned forever. If a reliable
   build ever falls out of other work they can be added as a convenience, but they buy no coverage the channel above
   lacks.
5. **An AppImage is the second channel, for users who want one file and no toolchain** — hand-rolled over
   python-appimage's relocatable **Python 3.14.6** runtime (manylinux2014/2_28, x86_64 and aarch64) —
   never Briefcase's backend, whose `linuxdeploy` step is the whole problem in point 2. Built (#210) in CI beside the
   other platforms' artifacts, and cheap: the recipe is a `requirements.txt`, a `.desktop` and an icon. One file
   for every distro, at the price of: FUSE (libfuse2 is not installed by default on Ubuntu 24.04+, so
   `--appimage-extract-and-run` or a fuse3 static runtime), a floor of glibc ≥ 2.34 on x86_64 and ≥ 2.38 on aarch64
   from the wheels, no uninstall, and #209 all the same — plus a full re-download per update, unless zsync update
   information is embedded. **Registration from inside an AppImage has one hard requirement:** the runtime exports
   `APPIMAGE` (the absolute path of the file the user launched), `APPDIR` (a temporary mount) and `OWD`, so the entry
   must be `Exec=$APPIMAGE %F` resolved from `APPIMAGE` — **never** from `sys.executable`, which points into
   `/tmp/.mount_XXXX/` and ceases to exist on exit. Since the user can move or rename the file at will, #209's
   "registered, but from a different location" state becomes the ordinary case rather than an edge one. The
   `--register`/`--unregister` flags work unchanged: the runtime claims only its own `--appimage-*` namespace and
   forwards every other argument verbatim ([[appendices.briefcase-packaging#linux-backends]]).

**What the self-registration half now is (#209).** `rehuco_agent.linux_registration` writes the three files above —
the desktop entry, the `application/x-rehuco` MIME package that makes its `MimeType` mean anything, and the icon in
the per-user `hicolor` theme — over generic XDG primitives in `borco_core.platforms.linux`, mirroring how the Windows
HKCU registration splits between `windows_registration` and `borco_core.platforms.windows`. It is reached from
`--register`/`--unregister` and from a **Desktop Integration** settings page, the same two call sites the Windows half
has. Three things are specific to Linux rather than copied: `Exec=` comes from `$APPIMAGE` when set, never from
`sys.executable`; the app declares `QGuiApplication.setDesktopFileName("io.github.borco.rehuco-agent")` so the Wayland
`app_id` and X11 `StartupWMClass` resolve back to that entry; and the page reports **four** states, not three —
"registered, but launching a different location" is separated from "registered, but out of date", because for an
AppImage the first is the ordinary case and re-registering is the fix. Inside Flatpak or Snap it refuses and says so:
the XDG directories are the package's, and a false "Registered." would be worse than an honest no.

**What the AppImage and the release workflow now are (#210, #208).** The recipe and the local build
(`make agent-appimage-build`) are detailed in [[appendices.briefcase-packaging#linux-backends]] — the
short version is that it's built and its `--register`/`--info`/`--version`/`--unregister` all verified
end to end, including `Exec=` resolving to the AppImage's own moved/renamed path exactly as designed.
`--info` (print whether registered, and where) and `--version` were added to the CLI alongside this —
plain flags rather than argparse's own exiting `action="version"`, so `rehuco-agent --info --register`
reports the prior state and then acts, on one command line, and so a packaged build has a fast headless
way to prove its interpreter and entry point work at all (`__main__.py`). `.github/workflows/release-agent.yml`
builds all three platforms — the Windows MSI and macOS `.app`/`.dmg` via the existing `make agent-dist-package`
(no new build logic, since Briefcase already produces both) alongside the AppImage — smoke-checks each with
`--version` (and the AppImage additionally under `QT_QPA_PLATFORM=offscreen` in a bare `ubuntu:24.04`
container, over a package floor found to be *larger* than qa.yml's own proven set —
[[appendices.continuous-integration#release-agent]]), and attaches all three to a GitHub Release. It triggers on a `rehuco-agent-X.Y.Z` tag
push — the one package with installers, tagged under the same `<package>-<version>` scheme #18 (PyPI
publishing) already settled for the other four, so one tag push fires both workflows rather than the
monorepo needing a second, repo-wide release concept. `workflow_dispatch` is the dry run: every build job
still runs, nothing gets published. PyPI publishing stays a separate workflow, `publish-packages.yml`: the
same tag scheme, OIDC trusted publishing, TestPyPI ahead of PyPI
([[appendices.continuous-integration#publish-packages]]).

**Two things this decision corrects, both verified rather than argued:**

- **Linux does not register the association declaratively.** None of the three Linux backends emits a `MimeType=` line
  or a MIME package, so `document_type` — which generates the macOS declaration — yields nothing there. #209 is
  not a convenience on Linux; it is the only association path, and every format above depends on it. That also means
  #209 no longer waits on this decision, and vice versa.
- **The interpreter floor is ours, not upstream's.** `PySide6`, `pyside6-qtads` and `pyside6-scintilla` all ship
  limited-API (`abi3`) manylinux wheels for x86_64 and aarch64, so nothing in the Qt stack pins a Python version or an
  architecture. What would keep a distro-Python `.deb` off Ubuntu 24.04 is the agent's own `requires-python = ">=3.14"`
  — deliberate, and the reason such a package would be pinned to Ubuntu 26.04-class releases. The uv channel sidesteps
  the question rather than answering it.

**The price of this choice, stated plainly:** the Linux audience is "someone who can install uv" — one command, no
root, and no Python knowledge beyond it — and PySide6 still needs the usual X/Wayland/GL/font system libraries, which
a desktop distro has and a minimal one may not — **and the AppImage does not escape that second half**, since
python-appimage bundles the interpreter and the wheels but not the host's system libraries. The uv prerequisite is what
point 5 removes; the Qt system-library one is common to both channels and is the thing to verify in a bare container
before promising "download and run".

Signing is untouched by this. On Linux it only arises if a `.deb`/`.rpm` is ever *hosted* in a repository rather than
downloaded directly, and the Windows/macOS signing gap stays open ([[appendices.open-questions#still-open]]).

### §16.8.2 How end users get it: the channels

[[[packaging-deployment#channels]]]

Distribution is as much a *channel* question as an artifact one. Every channel below feeds off a GitHub Release or
PyPI, so none of them needs hosting this project does not already have — and the per-channel work is deliberately
unfiled rather than promised.

| Channel | OS | What it needs from us | Gatekeeping |
| --- | --- | --- | --- |
| PyPI, via `uv tool install` / `uvx` | all three | nothing beyond publishing, which `publish-packages.yml` does on a tag | none |
| GitHub Release download | all three | just the artifact | none |
| **AppImage** on a Release | Linux | a python-appimage recipe and a CI job ([[packaging-deployment#linux-format]]) | none |
| **Scoop**, own bucket | Windows | a bucket repo of JSON manifests pointing at a release URL; a plain zip suffices | none — it is our repo |
| **winget** | Windows | a PR to `microsoft/winget-pkgs` with `InstallerUrl` + `InstallerSha256`. **No MSI required** — `portable` (winget ≥ 1.3) and `zip` (≥ 1.5) installer types exist, with `NestedInstallerFiles` naming the exe inside | PR validation |
| **Chocolatey** | Windows | a nuspec plus a PowerShell install script | moderation queue |
| **Homebrew cask**, own tap | macOS | a `homebrew-<name>` repo; the cask points at a hosted `.dmg`/`.zip`/`.pkg` | none for our own tap |
| apt / yum repository | Linux | GitHub Pages plus `reprepro`/`aptly` and a GPG key kept forever — **GitHub Packages has no apt or yum registry** (npm, RubyGems, Maven, Gradle, NuGet and Docker only) | none, but the key is ours to hold |

Two consequences worth stating. The Windows and macOS channels all want **the artifact #206 already has to produce**,
so they are downstream of it rather than separate decisions — a zip or `.dmg` on a Release feeds Scoop, winget and a
Homebrew tap with no extra build. And the Linux row is the one deliberately **not** walked
([[packaging-deployment#linux-format]]): `uv tool install` is already the Linux channel, with no repository, no signing
key and no per-distro build behind it.

**One payload fact that cuts across every channel, and it is worse installed than the wheel sizes suggest.** Measured
from each wheel's own `RECORD` inside the #206 bundles: **`PySide6-Addons` was 489 MB of the 818 MB macOS `.app` (60%)
and 437 MB of the 699 MB Windows bundle (62%)** — against 182 MB / 202 MB for `PySide6-Essentials`. A single framework,
`QtWebEngineCore`, accounts for 354 MB of the macOS figure: an entire Chromium, in an app that renders Markdown with
`QTextBrowser`. The source imports exactly five PySide6 modules — `QtCore`, `QtGui`, `QtNetwork`, `QtSvg`, `QtWidgets`
— every one of them in Essentials, and **no Addons module is referenced anywhere in the tree**. So the fix below was not
a trim but the deletion of three-fifths of every artifact. In compressed-wheel terms the Linux x86_64 Qt stack is ~258 MB, of
which **~175 MB was `PySide6-Addons`**.
It arrived because `pyside6-scintilla` required the `pyside6` meta-package, where
`pyside6-qtads` already required `pyside6-essentials` directly. **Resolved on 2026-07-28 (#211):** `pyside6-scintilla`
5.6.3.7 now requires `PySide6-Essentials` alone, and `rehuco-agent` and `borco-pyside` both name `PySide6-Essentials`
instead of the meta-package. The Windows MSI went from **215 MB to 80.6 MB** and its bundle from 699 MB to 264 MB; the
macOS `.app` went from **818 MB to 327 MB**. Two
traps found in the doing: the agent's floor was `pyside6-scintilla>=1.4.0`, a version that **never existed** — so every
real release satisfied it, including the six that pull the meta-package — and uninstalling `PySide6-Addons` from an
existing environment *breaks* `PySide6-Essentials`, because the two wheels share files in one `PySide6/` directory
(`uv sync --reinstall-package pyside6-essentials` repairs it; a fresh venv never sees it). The upstream half of the fix is
[borco/pyside6-scintilla#14](https://github.com/borco/pyside6-scintilla/issues/14), released as 5.6.3.7. The AppImage
(#210) therefore inherits the smaller payload instead of baking the old one in, which is what made this worth doing
first rather than treating the artifact size as fixed.

## §16.9 Auto-update

[[[packaging-deployment#auto-update]]]

The agent should detect a newer release, flag it, and offer to install. Design positions:

- **Version checking is cheap and uses a public source.** The repo is public, so either GitHub Releases or the PyPI
  metadata serves as the version oracle, via a small periodic poll.
- **Applying an update is the hard, OS-specific part**, with real prerequisites: a running application cannot overwrite
  itself in place, system-level installs need elevation, and signed/notarized artifacts are required or the OS blocks
  the download. The chosen approach is to **delegate the privileged install to the platform's installer** rather than
  hand-write a self-replacing updater.
- For the `uv tool` / pip channel, "update" is simply re-installing the newer package.

Code-signing / notarization is an unpriced prerequisite ([[appendices.open-questions#still-open]]). Auto-update is
end-user polish on the same track as [[packaging-deployment#app-identity]], deferred past the personal critical path
(plan: deferred).

## §16.10 Design resources

[[[packaging-deployment#design-resources]]]

- [#29: single icon master in top-level design/icons](https://github.com/borco/rehuco/issues/29)

Brand icons come from a **single Affinity Designer master**, `design/icons/icons.afdesign`, in a
**top-level `design/icons/`** folder — discoverable, and deliberately outside both `src/` (which
hatch ships, [[packaging-deployment#three-packages]]) and `docs_dir` (which mkdocs would otherwise bundle into the built
site). The
master **exports raw assets** (`favicon.svg`, `rehuco-agent.svg`, and a 1024-px `rehuco-agent.png`);
`make icons` derives the `.ico` and wires each consumer. Those exports are produced by a **manual
Affinity Designer export** and are **committed to git**, so anyone can build and run the project
**without Affinity Designer** — only re-exporting the master needs it (`design/icons/README.md` is
the contributor-facing summary). The rule is **reference the master's exports in place where a
consumer can reach `design/icons/`, and copy only where it cannot**:

- **Agent (Qt resources).** `main.qrc` references the svg in place with an alias
  (`../../../../design/icons/rehuco-agent.svg` → `:/icons/rehuco-agent.svg`), so the runtime
  resource path is stable regardless of the on-disk location. `make qrcs` compiles the qrc into
  `main_rc.py` (gitignored, regenerated); **the wheel ships that `.py`, not the raw images**, and
  QML reads the same `qrc:/icons/…`. No copy.
- **Launcher ([[appendices.windows-dev-launcher#overview]]).** The dev launcher's `CMakeLists.txt` points the RC
  compiler at
  `design/icons/rehuco-agent.ico` in place; it is embedded into the exe's PE resources for the
  Explorer / taskbar / pin icon. No copy.
- **Docs site.** mkdocs-material resolves `theme.favicon` / `theme.logo` **relative to `docs_dir`
  and cannot read outside it**, so this is the one consumer that needs copies: `make docs-icons` copies
  `favicon.svg` → `docs/assets/images/favicon.svg` and `rehuco-agent.svg` →
  `docs/assets/images/logo.svg` (each a real make target, so it re-copies only when the source is
  newer). Both copies are **generated and gitignored**, like every other derived asset here, so
  `docs-build` and `docs-serve` depend on `docs-icons` and the publish workflow runs it before
  deploying. The consequence to know: a bare `uv run mkdocs serve` on a fresh checkout renders
  without them until `make` has produced them once.

**Workflows that touch these assets:**

- **`make icons`** — builds `rehuco-agent.ico` by **downscaling the 1024-px PNG master** to
  `16,24,32,48,64,128,256` (reliable; rasterizing the SVG via ImageMagick is not — the naive
  per-SVG `.ico` pitfall is [[appendices.windows-dev-launcher#create-too-many-icons]]), builds the
  macOS `.icns` and the WiX installer bitmaps, and fans out the docs favicon/logo. **Everything it
  produces is generated, hence gitignored** — `.ico`, `.icns`, `.bmp` and the two docs copies alike.
- **`make docs-icons`** — the docs half of the above on its own: two `cp`s, no ImageMagick. Split out
  so `docs-build`/`docs-serve` can depend on it without requiring a toolchain the site never needs.
- **`make qrcs`** — `pyside6-rcc` compiles each `.qrc` into `<name>_rc.py`, embedding the aliased
  svg. It **no longer depends on `make icons`**: the qrc embeds only the svg (referenced from
  `design/icons/`), not the `.ico`, so a resource rebuild needs no ImageMagick.
- **`make uis`** — `pyside6-uic` regenerates the `*_ui.py` (which import `*_rc`); depends on
  `qrcs`.

**Conventions:**

- **SVG export size is irrelevant** — SVG is resolution-independent; keep a **square `viewBox`**
  and **pure-vector paths** (no embedded rasters). mkdocs sizes the header logo via CSS, not the
  SVG's intrinsic dimensions, so there is no "logo size" to tune in the export.
- **Keep the PNG master at 1024 px** — ample for the 256-px `.ico`, and it future-proofs a macOS
  `.icns` (512/1024).
- **The `.ico` is derived from the PNG master**, never from the SVG.
- **Masters stay out of `src/` and `docs_dir`**, so neither the wheel nor the built site bundles
  the editable `.afdesign`.
