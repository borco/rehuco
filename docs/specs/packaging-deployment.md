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
    rehuco-node/          # the local node: rehuco-core + borco-core; FastAPI/zeroconf once the web pages come
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

The QNAP TS-230 is used as a **NAS**, not as a compute host. It serves its storage over the existing Samba (SMB) share,
and that share is the system of record ([[architecture-design#why-distributed]]): every machine's agent and node reach
the content through their own mount, treating it as a local path. Nothing of rehuco's runs on the TS-230, and the glibc
constraint ([[packaging-deployment#glibc-canary]]) plays no role in deployment. Because agents keep running while the
TS-230 is powered off for long stretches, every mount is treated as possibly offline — see
[[mounts-and-storage#offline-mounts]].

**What Samba gives the design, measured on the TS-230 (#502, #503):** SMB2 `CHANGE_NOTIFY` backed by inotify on the
server (`kernel change notify = yes`, the default), which is how every machine learns of another's writes
([[mounts-and-storage#out-of-band]]); and a server-side atomic exclusive create, which is the lock file
([[sync#lock-file]]).

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
   python-appimage's relocatable **Python 3.14** runtime (manylinux2014/2_28, x86_64 and aarch64) —
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

**What the self-registration half now is (#209).** `rehuco_agent.registration_linux` writes the three files above —
the desktop entry, the `application/x-rehuco` MIME package that makes its `MimeType` mean anything, and the icon in
the per-user `hicolor` theme — over generic XDG primitives in `borco_core.platforms.linux`, mirroring how the Windows
HKCU registration splits between `registration_windows` and `borco_core.platforms.windows`. It is reached from
`--register`/`--unregister` and from the **Desktop Integration** frame of the System Integration settings page, the
same two call sites the Windows half has. Three things are specific to Linux rather than copied: `Exec=` comes from
`$APPIMAGE` when set, never from `sys.executable`; the app declares `QGuiApplication.setDesktopFileName("io.github.borco.rehuco-agent")` so the Wayland
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
first rather than treating the artifact size as fixed. The in-app player (#317) brings about 21 MB of the wheel
back, on purpose and pruned to what playback needs ([[packaging-deployment#qt-multimedia]]).

**The same measurement, applied before the fact: the video-duration probe (#224).** Nothing in the tree could read a
video container, and the candidates differ by more than an order of magnitude in what they add to every artifact —
measured by installing each into an empty target on Windows and summing it:

| Candidate | Installed | What it bundles | Reads `.ts` / `.vob` |
| --- | --- | --- | --- |
| **`pymediainfo` 7.0.1** | **8 MB** (3.3 MB wheel) | `libmediainfo`, in the wheel | yes |
| `hachoir` 3.3.0 | 3 MB | nothing — pure Python | **no** (answers nothing for either) |
| `av` (PyAV) 18.0.0 | 67 MB | 25 FFmpeg DLLs | yes |
| `imageio-ffmpeg` 0.6.0 | 84 MB | one 87 MB `ffmpeg.exe` | yes |
| `ffmpeg-binaries` 1.1.0 | 244 MB | FFmpeg, plus `requests` and `patool` | yes |
| `ffprobe` on `PATH` | 0 MB | nothing — the user's own install | yes |

All of them agreed on duration to the millisecond over the same nine containers, so **correctness did not decide it and
payload did**. `pymediainfo` publishes `py3-none-<platform>` wheels carrying the library for all three targets
(`win_amd64`, `macosx_10_10_universal2`, `manylinux_2_27_x86_64`) — no compilation, no CPython ABI tag, and a glibc
floor **below** the one the Qt stack already imposes ([[appendices.briefcase-packaging#linux-backends]]), so it adds no
constraint to any of the three installers. It is therefore the **default** backend, with `ffprobe` the deliberate
alternative for a machine that already has FFmpeg rather than the fallback for one that has neither. `hachoir` is the
cautionary entry: it is the smallest and the only one needing no binary at all, and it silently answers *no duration*
for MPEG-TS and VOB — two containers on tc4's own extension list — which is exactly the silent-zero failure the probe
contract refuses.

### §16.8.3 External tools

[[[packaging-deployment#external-tools]]]

- [#521: feat: Tools settings page — optional external tools (ffprobe, VLC, ffmpeg): detect, browse, version gates, install instructions](https://github.com/borco/rehuco/issues/521)

Some programs the app uses cannot ship with it: too large, GPL, or non-free. Each is an **external tool**: a
`ToolDescriptor` in `rehuco-core` (Qt-free) says what it is for, which features need it, why it is not bundled, where
each OS keeps it, how its version is read, its minimum and its blocklist. A `ToolLocator` turns a descriptor into
candidates, each with a version and a status. One **Tools** settings page ([[appendices.settings-pages#tools-page]])
sets them all up. The tracer had one tool, **FFmpeg** (`ffmpeg` and `ffprobe` in one folder, the duration probe's
external backend, [[field-schema#duration-size]]); **VLC** (the `vlc` executable and, what the app uses of it, its
`libvlc` shared library, the Videos page's in-app VLC engine, #318, #319) joined it, and the conversion `ffmpeg` (#520) arrives with the feature that needs it.

- **The app never downloads a tool.** The docs site's [External Tools](../external-tools.md) page says where each one
  comes from, one section per tool under a fixed anchor (`#ffmpeg`, `#vlc`, `#ffmpeg-libraries`); each tool's frame links
  to its section.
- **Detection finds every install**, in the current OS's default places — Windows: `PATH`, winget, scoop,
  chocolatey, Program Files; macOS: `PATH`, `/opt/homebrew`, `/usr/local`, MacPorts; Linux: `PATH`, `/usr/bin`,
  `/usr/local/bin` — and the newest usable one is chosen unless the user picks another. A folder of links to the
  executables (winget's `Links`), or of scoop's shims (a launcher beside a `.shim` file naming the real executable),
  counts as the install it points at, so one install is listed once; a linked folder (scoop's `current`) keeps its own
  path, so a choice of it survives an update. **Browse** picks a custom install and takes the executable, its folder,
  or an unpacked archive's root holding a `bin`.
- **It runs once, in the background.** The agent starts a thread of its own at launch that visits each tool: one never
  searched for is searched for, one already searched for is only **verified** — its stored installs are kept while their
  executables still exist, with nothing searched for and no version read. So the first start searches, a later one
  costs a few file checks, and a run interrupted by quitting resumes with the tools it had not reached. A tool searched
  for that found nothing is not searched for again until the user presses **Detect**, which forces the search. The
  thread is a daemon, so quitting never waits for it.
- **What was found is stored, beside the user's path, and both are kept.** Per tool the settings file holds the path
  the user chose (empty for the best install found) and the detection: whether the tool was searched for, and every
  install found, each with its version and status. A custom path never removes the detection, so giving it up finds
  what was found before. Recording a result changes memory only; the file is written with the other settings when the window
  closes and when the Tools page applies, never per tool. A feature **reads** the detection and searches for nothing.
- **Versions only, no checksums.** A descriptor has a minimum and a blocklist of versions known not to work, each with
  its reason. A version newer than any tested, or one that cannot be read (a git build), is **untested** and allowed:
  an allowlist would lock out everyone who updated.
- **Status** per candidate: *usable*; *untested* (usable); *not runnable* (the executable does not start); *too old*;
  *blocklisted*, with the reason; for the playback libraries (#580) *no libraries* (a static build), *wrong major
  version*, *incomplete* and *wrong architecture* (a 32-bit or ARM build in a 64-bit x86 process), each its own status
  rather than a version failure; for VLC, *no libraries* is a static or sandboxed install (a snap or flatpak VLC) whose
  `libvlc` is not there to load, and *incomplete* one missing its core library or plugins. **Only usable installs
  are kept** by a Detect; each rejected one is logged once at WARNING with its folder and reason (#319, #592).
  *Missing* is a path with nothing at it.
- **The version is read without loading anything into the agent**: by running the tool (`ffprobe -version`), from the
  vendor's own metadata where the executable prints nothing, and for a library in a child process.
- **A chosen path is judged when used**, its version read once and cached by path and modification time. A feature
  whose tool is unusable is disabled with the reason and a way to the Tools page, rather than failing at use; one that
  was usable and later breaks, as a tool updated or a share unmounted, fails with the candidate's own reason.
- **Two kinds of FFmpeg.** The **program** takes any version at or above its minimum. The **playback libraries** (#580)
  replace the FFmpeg Qt Multimedia bundles ([[plugins#in-app-player]]) and must match the major versions the shipped
  PySide6 bundles, read from its own DLL names, never from a number in the code. They are a descriptor of their own,
  `FfmpegLibrariesTool`, registered on Windows only, the one platform measured. A build is judged by its file names
  first and then **tried in a child process**: the agent run again with a hidden `--probe-ffmpeg-libraries` flag that
  loads the five libraries and writes its answer to the `--output` file, since the packaged exe prints nowhere and a
  build that crashes the process it loads into must not be the agent. The agent loads a build, by full path in
  `avutil`, `swresample`, `swscale`, `avcodec`, `avformat` order, only from `__main__` at start, ahead of the import of
  Qt Multimedia, and only when the Videos page chose it (`PlaybackLibraries`); a build that is gone or will not load
  leaves Qt's own in use, with the reason kept for the Videos page and the log. Qt's own folder, on `PATH` in a
  development environment, is never listed as a build.
- **Paths are machine-local, never remotely settable** ([[discovery-trust-access#remote-admin]]). A node locates its own
  tools through the same `ToolLocator`, configured from its own config, and never sees the agent's paths.

### §16.8.4 Qt Multimedia in the bundle

[[[packaging-deployment#qt-multimedia]]]

- [#317: feat: in-app video player dock — Qt Multimedia surface, transport bar, keyboard, folder playlist, resume](https://github.com/borco/rehuco/issues/317)

The in-app player ([[plugins#in-app-player]]) plays through Qt Multimedia, which lives in `PySide6-Addons` — the wheel
[[packaging-deployment#channels]] cut from every artifact. So the agent names it again, `PySide6-Addons` and never the
`PySide6` meta-package, and the build keeps only what playback needs of it.

**The prune.** `tools/prune_pyside_addons.py` runs on the bundle's `app_packages` between `briefcase build`, which
installs the wheel, and `briefcase package`, which wraps the bundle: `make agent-dist-build` and
`make agent-dist-package` both do it, on Windows and macOS. It removes every file the Addons wheel's `RECORD` names,
except a keep list and except what `PySide6-Essentials` owns too — 64 files in 6.11, `PySide6/__init__.py` among them.
That is why a remove list, which is all Briefcase's own `cleanup_paths` can be, was not the tool: it would have to
name every module, and a module a later release adds would ship. Here it is removed without anyone listing it. The keep
list is regular expressions per platform, because the FFmpeg libraries carry their major version in their names and it
moves with PySide6 (`avcodec-61` in 6.11, `avcodec-63` in 6.12); a pattern that matches nothing fails the build rather
than ship a player that cannot play.

Measured against the real wheels' `RECORD`, with the files `PySide6-Essentials` owns left out of both columns:

| PySide6 | Platform | Addons wheel | Kept |
| --- | --- | --- | --- |
| 6.11.1 | Windows | 458 MB | 21.5 MB |
| 6.12.0 | Windows | 105 MB | 22.7 MB |
| 6.11.1 | Linux | 438 MB | 23.1 MB |
| 6.12.0 | Linux | 160 MB | 24.4 MB |
| 6.11.1 | macOS | 884 MB | 43.5 MB |
| 6.12.0 | macOS | 251 MB | 46.0 MB |

The macOS wheel is universal2, so every binary holds both architectures. On a real Windows build (6.12.0) the bundle's
`app_packages` went from **424 MB to 343 MB**, and the installer is 118 MB.

**Four things found only by running it**, none of them visible in the wheels' file lists:

- **The bundle takes PySide6 from PyPI, not from `uv.lock`.** Briefcase pip-installs `PySide6-Essentials>=6.9` and got
  6.12.0 while the lock holds 6.11.1, so the FFmpeg libraries a bundle carries are not the ones a developer's venv has.
- **The wheels hold each FFmpeg library two or three times**, flattened out of their symlinks — on Linux
  `libavcodec.so`, `libavcodec.so.63` and `libavcodec.so.63.1.101`, 15 MB each. Nothing loads the unversioned and the
  full-version copies, so the macOS and Linux lists keep the SONAME only. Keeping them all made the Linux figure 62 MB
  and the macOS one 80 MB.
- **The Linux FFmpeg plugin needs `libQt6FFmpegStub-va-x11.so.2`**, which a first pattern missed for the digit in its
  name: the plugin silently failed to load (`Failed to create QVideoSink`) and the clip showed nothing.
- **`import PySide6.QtMultimedia` needs the system library `libpulse.so.0` on Linux**, which `Qt6Multimedia` links. The
  document's player dock imports it, so this is a start-up dependency, not a playback one: the agent does not start
  without it. `libpulse0` joins the package floor of the bare-container check (`ci/verify-agent-appimage.sh`,
  [[packaging-deployment#linux-format]]) and of the CI and release workflows' Qt libraries.

**The smoke test.** A bundle pruned too far builds, installs and starts, and fails only when a reader opens a video, so
the release workflow plays one. `rehuco-agent --check-playback CLIP`, a flag left out of `--help`, plays the clip into
a video sink with no window and no sound, and exits 0 only once a picture has arrived and the position has moved,
within ten seconds. The clip is `ci/playback-check.mp4`, three kilobytes of H.264. The workflow runs it on the built
Windows exe and macOS app and on the AppImage, beside `--version`. It was shown able to fail: with the FFmpeg plugin
hidden from the built Windows bundle it exits 1, and with it restored, 0.

**What was verified, and what was not.** Windows: built, pruned, packaged, and the built exe plays the clip. Linux: in a
clean venv of 6.12.0 the prune took 403 MB to 270 MB and the clip played before and after. macOS: not run. The keep list
matches the real wheels' `RECORD` for 6.11.1 and 6.12.0, and the load commands of the ten kept binaries, read out of
the wheel, name nothing outside the keep list, `PySide6-Essentials`, `shiboken6` and the system; the first release dry
run is the proof. **The AppImage is not pruned:** python-appimage installs the wheels and builds the image in one
step, so it carries the whole Addons wheel, and cutting it is a step that image build does not have a place for.

A development environment installs the whole wheel too, 437 MB of it in 6.11.1; only a bundle is pruned.

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

Brand icons come from a **single Affinity Designer master**, `design/icons/_icons-master.afdesign`, in a
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

## §16.11 App folders

[[[packaging-deployment#app-folders]]]

- [#405: docs: spec root caching, borrowing UI, and per-file watch progress](https://github.com/borco/rehuco/issues/405)

**The agent and the node share their files, per machine and OS user**, under the organization folder every borco app
uses. What they keep: both apps' settings side by side (`rehuco-agent.ini`, and the node's own settings file), their
caches (`.rehudb`, [[data-model#local-file-trio]]), and their durable local state — the retention store
([[mounts-and-storage#durable-retention]]), the saved task queue, the open-document session and the window and
dock layouts (JSON files, not the `.ini`, #404), the scraper browser's persona, crash dumps. Where it
goes follows each platform's own convention:

| Platform | Settings | Durable state | Caches |
| --- | --- | --- | --- |
| Windows | `%LOCALAPPDATA%\borco\rehuco` | same folder | same folder |
| macOS | `~/Library/Application Support/borco/rehuco` | same folder | same folder |
| Linux | `$XDG_CONFIG_HOME/borco/rehuco` (`~/.config`) | `$XDG_DATA_HOME/borco/rehuco` (`~/.local/share`) | `$XDG_CACHE_HOME/borco/rehuco` (`~/.cache`) |

- **One folder on Windows and macOS.** Neither platform separates settings from data by convention as Linux does, so
  everything sits in one place there — one answer to "where are rehuco's files".
- **Local, not roaming, on Windows.** The Roaming profile is meant for small settings that follow a user between
  machines; this folder holds gigabytes of retained screenshots and caches that describe *this* machine's roots, so it
  belongs in Local. One place was preferred over splitting settings (Roaming) from data (Local).
- **Linux follows XDG**, as its users and tools expect: settings under the config directory, durable state under the
  data directory, and disposable caches under the cache directory, which backup tools and cleaners know to skip. The
  `XDG_*` variables are honored when set; the paths in parentheses are their defaults.
- **Images handed to other apps are staged under the caches**, in `staged/` (#395): byte-identical copies of the images
  dragged or copied out, named by where they came from ([[reference-images#modes]]). They outlive the drop and a later
  paste, and the agent deletes the ones unused for seven days when it starts.
- **Not everything in it is disposable.** Caches can be deleted and rebuilt; the retention store of a removable root,
  the saved task queue with its pending saves ([[sync#pending-saves]]), and the node's sessions and `.borrow`
  snapshots ([[data-model#local-file-trio]]) cannot. Deleting the folder wholesale loses them.
- **Borrowed copies never go here** ([[borrowing#agent-ui]]): one borrow can be many gigabytes, so each node's borrow
  folder is the user's choice.
- **One folder, because the agent and the node run as the same OS user** ([[nodes#two-roles]]): the node is the
  agent's child and reads the same `.rehuco` and settings. A system service would run under its own account with a
  folder of its own, which is one of the costs that kept it out for now ([[nodes#overview]]).
- **The move from the earlier location is manual.** Before #412 the agent's files sat in a `borco/rehuco-agent` folder
  beside its `.ini` (#361) — Roaming on Windows, `~/.config` on Linux — and its caches in `borco/rehuco-agent` under
  the platform's cache location. They are moved once, by hand — or deleted and let the app recreate them — and no
  migration code is written for it.
- **The agent's files sit loose in these folders**, with no subfolder of their own; the node keeps its heartbeat, its
  log and later its sessions under `node/` ([[multiplicity#instances]]).
- **A run can be pointed at a folder of its own** (#494): `rehuco-agent --settings-dir DIR`, or
  `REHUCO_AGENT_SETTINGS_DIR` (the flag wins). Everything above then lives in `DIR` instead —
  settings, durable state and caches alike, the layout of Windows and macOS — and the run has its own single instance ([[nodes#single-instance]]). It keeps a development build off the installed one's
  files while their formats diverge; the window title names the folder.
