# §16. Code Organization, Packaging, and Deployment

A monorepo with **uv workspaces** is the chosen structure, driven by three concrete pains: refactoring code between the shared library and the apps (currently a multi-repo/submodule dance of coupled commits), tooling confusion over *which* `.venv` is active (a multi-root VSCode layout has one venv per root, and tools — including AI coding assistants — guess wrong), and independent PyPI publishing of the shared libraries.

## §16.1 Why uv workspaces

- **One shared `.venv` at the workspace root**, containing every member as an editable install. This eliminates the "which venv?" ambiguity at its source: there is exactly one environment, every package is always importable from it, nothing to guess. (This is the strongest single reason for the move.)
- **Atomic cross-package refactors.** Moving a widget from an app into the shared library becomes one commit in one repo, instead of a commit in the submodule plus a pointer-bump commit in the consumer.
- **Single lockfile, consistent versions** across members — which for a set of sibling PySide6 apps sharing a library is a benefit (it forces version compatibility), not a limitation.

The one real constraint workspaces impose: all members resolve against **one dependency set**, so two members needing conflicting versions of the same package would fail to resolve. For this project (all the author's own apps over a shared Qt-era stack) that's acceptable and even desirable.

## §16.2 Three packages, mapping onto the node/agent/shared-library split

- [x] [#12: Add borco-core and borco-pyside generic packages; move ApplicationSingleton to borco-pyside](https://github.com/borco/rehuco/issues/12)

The packaging boundary mirrors the architecture's node/agent split (§5.1):

```txt
rehuco/                   # monorepo root
  pyproject.toml          # virtual workspace root: [tool.uv.workspace] only, no [project]
  uv.lock                 # single lockfile
  .venv/                  # the one shared environment (development only)
  packages/
    rehuco-core/          # shared library: field toolkit, .rehu model, plugin base — PUBLISHABLE
    borco-core/           # generic, non-rehuco utilities (no GUI dep) — temporary guest, moving out
    borco-pyside/         # generic, non-rehuco PySide widgets/utilities — temporary guest, moving out
    pyside6-scintilla/    # PUBLISHABLE
    pyside6-lexilla/      # PUBLISHABLE
  apps/
    rehuco-node/          # headless service: depends on rehuco-core + FastAPI/uvicorn/zeroconf
    rehuco-agent/         # desktop GUI: depends on rehuco-core + PySide6/scintilla/ads
```

The **virtual workspace root** (no `[project]` table, only `[tool.uv.workspace]`) is a pure organizational container — it can't itself be published and holds no app code, keeping the root clean. Shared libraries are publishable leaf packages (they depend only on PyPI packages, never on the apps, so they carry no workspace-internal dependencies that would block publishing).

The `borco-*` packages (`borco-core`, `borco-pyside`) are **generic, non-rehuco** utilities under the author's own `borco` namespace — a home for reusable code with no rehuco coupling. They are **temporary guests** in this monorepo, hosted here only while their APIs settle, and are **scheduled to move to their own repository** (or a separate generic monorepo) later; nothing rehuco should assume they stay here. `borco-core` is GUI-free; `borco-pyside` carries the Qt-dependent pieces and depends on `borco-core`. Together they are the successor of the earlier planned generic PySide package and of the old standalone PySide utility library. The first piece to land is `borco_pyside.core.ApplicationSingleton` — the single-instance guard consumed by `rehuco-agent` (§16.2 tree).

## §16.3 PyPI publishing and `uv tool install`

- Each member has its own `pyproject.toml` (name, version, build backend) and **publishes to PyPI independently** — `uv build --package rehuco-core && uv publish`. The monorepo structure is invisible to PyPI; it just sees a normal wheel.
- The node and agent are installable as tools: **`uv tool install rehuco-node`** (ideal — headless service, console entry point) and **`uv tool install rehuco-agent`** (works for the GUI; native installers / file-association registration are a later polish for wider distribution (§16.8), not needed for the author's own machines).
- **Three packages, not one-package-with-extras.** Extras were considered (`rehuco[node]` / `rehuco[app]`) but rejected: extras are *additive and cannot subtract a base dependency*, so any GUI dependency reachable from the base would still be pulled by `rehuco[node]` — adding unwanted GUI overhead to a headless service. Separate packages make "the node has no GUI dependencies" **structural rather than carefully-maintained**, and let each package carry its own `requires-python` floor.

## §16.4 The TS-230 as NAS: SMB mount, not a node host

The QNAP TS-230 is used as a **NAS**, not as a compute host. It serves its storage over the existing Samba (SMB) share. `rehuco-node` runs on capable hardware (Mac mini, always-on Linux box) and accesses TS-230 content via that SMB mount — treating it as a local path. No node needs to run on the TS-230 itself, and the glibc constraint (§16.5) plays no role in deployment.

This is already an option the architecture anticipated (§9.3): the box owning the disks doesn't need to run its own node if another always-on machine covers the serving role via a mount. Choosing it as the default simplifies deployment significantly. Because the always-on node keeps running while the TS-230 may be powered off for long stretches, the node must tolerate the mount being offline without blocking — see §9.9.

**Atomic-save invariant over SMB (§4.9):** an SMB `rename` is a server-side operation — the server executes it locally; no data crosses the network. The temp file must be written into the same directory as the target so that source and destination are on the same server-side filesystem. With that constraint, the write-temp-then-rename pattern is correct and cheap over SMB.

**The monorepo workspace remains the development environment only** — it is never synced to a remote host. Deployment installs individual published packages: `uv tool install rehuco-node` on any capable box, `uv tool install rehuco-agent` on GUI machines.

## §16.5 TS-230 glibc canary — historical findings

Since the node does not run on the TS-230 (§16.4), the glibc canary is **not an active requirement**. The findings below are kept as a reference in case direct QNAP deployment is ever reconsidered.

The initial canary confirmed that all planned node dependencies install and import successfully on glibc 2.23 / aarch64 — so the QNAP-as-node option remains technically viable. The automated CI canary (§16.5.2) has been **suspended** as it guards a deployment model that is no longer in use.

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

- [x] [#5: spike: QNAP/glibc dependency canary](https://github.com/borco/rehuco/issues/5)

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

- [x] [#9: feat: container canary + CI workflow for node glibc compatibility](https://github.com/borco/rehuco/issues/9)

The canary runs at three tiers, ordered fastest → most authoritative:

1. **Local / Mac mini** — native aarch64, no QEMU overhead. Run `ci/node-canary.sh` inside the container
   locally (`--platform linux/arm64` is a no-op on M-series hardware). Fast feedback when bumping dependencies.
2. **GitHub Actions** — QEMU emulation of aarch64 on an x86_64 runner (`.github/workflows/node-canary.yml`).
   Triggers on push to canary-related files and on a weekly schedule. Keeps the compatibility promise
   continuously verified without manual effort.
3. **Physical TS-230 (`ssh nas`)** — ground-truth on real glibc 2.23 hardware. On-demand only; see §16.5.1
   for initial run notes and the `TMPDIR` warning.

`ci/node-canary.sh` installs rehuco-node's direct PyPI dependencies inside
`quay.io/pypa/manylinux2014_aarch64` (glibc 2.17 floor, more conservative than the TS-230's 2.23) and
smoke-imports each one. A missing `manylinux2014_aarch64` wheel or a glibc-version mismatch exits non-zero.

## §16.6 Migrating existing repos

**Decided: start the monorepo fresh.** Per-repo git history of the old apps isn't valued enough to preserve (the author is comfortable starting clean — "what's another repo"). The old rehuco-predecessor repos (`resource-hub`, `tutcatalog5`, `tutcatalog4`) are not grafted in. This avoids the `git subtree`/`git-filter-repo` fiddliness entirely. The generic PySide utilities that used to live in a standalone package are likewise reintroduced fresh as the `borco-*` packages (§16.2) rather than grafted in — no old clone or remote needs to survive.

## §16.7 Dependency licensing policy

**Principle: the choice of the final application's license must stay with the author, not be forced by a dependency.** GPL is fine *by deliberate choice* for a final app; being *compelled* into GPL by a linked library is not acceptable — it removes the author's freedom and entangles the reusable libraries (`rehuco-core`, `pyside_ibo`, etc.) that are meant to be independently publishable under whatever license the author picks. (This principle is already evidenced by the author writing an MIT-licensed `pyside6-scintilla` rather than depending on a copyleft alternative.)

Concrete consequence for **docking**:

- **Use `pyqtads` (Qt-Advanced-Docking-System), not KDDockWidgets.** Both are mature and feature-comparable (detach/float/nest/auto-hide/delete-on-close), and KDDockWidgets is in some respects the more capable *framework* (KDAB pedigree, native QML docks, deeper customization). But:
  - **KDDockWidgets is GPL 2.0/3.0** (or paid commercial). Linking it makes the *entire agent* a GPL combined work — cascading into the publish plan (§16.3) and risking entanglement of the reusable libraries. This is a property of the license, not something the binding/packaging can engineer around.
  - **`pyqtads` is permissively licensed (LGPL)** — it can be linked from an app of any license without forcing the app's license — **and ships prebuilt PySide6/PyQt6/PyQt5 bindings on PyPI**, so it drops into the uv workspace as a normal dependency with no build step.
- The packaging objection to KDDockWidgets (no PyPI wheel; bindings must be built from source via shiboken+CMake+libclang) is one the author *could* solve — the same CI-built-binding work already done for `pyside6-scintilla` (shiboken) and `pyside6-lexilla` (nanobind). So bindings are **not** the blocker. **The license is the blocker**, and it is not solvable by effort.
- KDDockWidgets is therefore foreclosed for this project. The QML-in-`pyqtads` approach (QQuickWidget hosted in a widget dock) was **re-verified on current versions** by spike #4 (§16.7.1) and holds; the fallback — constraining how QML is used (non-detachable docks, reduced QML footprint) — is held in reserve, **not** needed, and switching to KDDockWidgets stays foreclosed regardless.

### §16.7.1 QML-in-`pyqtads` regression check (spike #4)

- [ ] [#4: spike: pyqtads + QML integration regression check](https://github.com/borco/rehuco/issues/4)

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
(§13.4's "clicking a resource opens its viewer dock") — a multi-pane shell, not a single-window
form. The three-line wiring snippet and the closed-dock-size workaround stay in
`spikes/pyqtads-qml/` as a working reference until that slice consumes them (then the spike is
deleted and this issue closed).

## §16.8 Desktop distribution, file association, and app identity

Distribution splits by audience, structurally (as the package split does, §16.2):

- **`rehuco-core` and `rehuco-node` are pure PyPI** (§16.3) — a library and a headless service; no GUI identity, no file association.
- **`rehuco-agent` is dual-channel.** `uv tool install` suffices for the author's own machines and developers (§16.3); wider end-user distribution additionally needs a **native app identity** — icon, file association, taskbar pin/running indicator, an installer — that a bare install cannot provide.

Two design facts shape the choice:

- **File association is OS-specific, and macOS is the binding constraint.** Only a real application bundle can be a document type's default handler there, and the opened path is delivered as an in-process event rather than a command-line argument — so it must reach the already-running single instance (§5.4). Windows and Linux register the association declaratively and need no elevation.
- **Windows app identity (icon / pin / running) is an identity-registration concern, not a "must be a compiled binary" one.** A prior version (`resource-hub`) achieved a correct taskbar icon/pin/running indicator only from a frozen PyInstaller build, but the real requirement is a stable per-application identity plus an ordinary per-app launcher — both available without freezing (the standard entry-point launcher already serves). Freezing the app into a single binary is therefore **not** required.

**Decision: package end-user builds with Briefcase, not PyInstaller.** Briefcase does not freeze — it pairs a thin launcher with an embedded interpreter and the app's source, and declares icon, identity, file association, and installer from `pyproject.toml`, so the OS-specific registration is generated rather than hand-maintained. The deciding reasons are **reduced fragility and declarative app identity**, not build speed. MSIX is a possible later upgrade for the strongest Windows identity. This is wider-distribution polish — not needed for A0 or the author's own machines — and the file-association and single-instance mechanics it rests on are de-risked by a dedicated spike (plan: Pre-work) before A0 relies on "double-click opens."

## §16.9 Auto-update

The agent should detect a newer release, flag it, and offer to install. Design positions:

- **Version checking is cheap and uses a public source.** The repo is public, so either GitHub Releases or the PyPI metadata serves as the version oracle, via a small periodic poll.
- **Applying an update is the hard, OS-specific part**, with real prerequisites: a running application cannot overwrite itself in place, system-level installs need elevation, and signed/notarized artifacts are required or the OS blocks the download. The chosen approach is to **delegate the privileged install to the platform's installer** rather than hand-write a self-replacing updater.
- For the `uv tool` / pip channel, "update" is simply re-installing the newer package.

Code-signing / notarization is an unpriced prerequisite (§A01.2). Auto-update is end-user polish on the same track as §16.8, deferred past the personal critical path (plan: deferred).
