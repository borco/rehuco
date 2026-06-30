# §16. Code Organization, Packaging, and Deployment

A monorepo with **uv workspaces** is the chosen structure, driven by three concrete pains: refactoring code between the shared library and the apps (currently a multi-repo/submodule dance of coupled commits), tooling confusion over *which* `.venv` is active (a multi-root VSCode layout has one venv per root, and tools — including AI coding assistants — guess wrong), and independent PyPI publishing of the shared libraries.

## §16.1 Why uv workspaces

- **One shared `.venv` at the workspace root**, containing every member as an editable install. This eliminates the "which venv?" ambiguity at its source: there is exactly one environment, every package is always importable from it, nothing to guess. (This is the strongest single reason for the move.)
- **Atomic cross-package refactors.** Moving a widget from an app into the shared library becomes one commit in one repo, instead of a commit in the submodule plus a pointer-bump commit in the consumer.
- **Single lockfile, consistent versions** across members — which for a set of sibling PySide6 apps sharing a library is a benefit (it forces version compatibility), not a limitation.

The one real constraint workspaces impose: all members resolve against **one dependency set**, so two members needing conflicting versions of the same package would fail to resolve. For this project (all the author's own apps over a shared Qt-era stack) that's acceptable and even desirable.

## §16.2 Three packages, mapping onto the node/agent/shared-library split

The packaging boundary mirrors the architecture's node/agent split (§5.1):

```
rehuco/                   # monorepo root
  pyproject.toml          # virtual workspace root: [tool.uv.workspace] only, no [project]
  uv.lock                 # single lockfile
  .venv/                  # the one shared environment (development only)
  packages/
    rehuco-core/          # shared library: field toolkit, .rehu model, plugin base — PUBLISHABLE
    pyside_ibo/           # generic PySide widgets/utilities — PUBLISHABLE
    pyside6-scintilla/    # PUBLISHABLE
    pyside6-lexilla/      # PUBLISHABLE
  apps/
    rehuco-node/          # headless service: depends on rehuco-core + FastAPI/uvicorn/zeroconf
    rehuco-agent/         # desktop GUI: depends on rehuco-core + PySide6/scintilla/ads
```

The **virtual workspace root** (no `[project]` table, only `[tool.uv.workspace]`) is a pure organizational container — it can't itself be published and holds no app code, keeping the root clean. Shared libraries are publishable leaf packages (they depend only on PyPI packages, never on the apps, so they carry no workspace-internal dependencies that would block publishing).

## §16.3 PyPI publishing and `uv tool install`

- Each member has its own `pyproject.toml` (name, version, build backend) and **publishes to PyPI independently** — `uv build --package rehuco-core && uv publish`. The monorepo structure is invisible to PyPI; it just sees a normal wheel.
- The node and agent are installable as tools: **`uv tool install rehuco-node`** (ideal — headless service, console entry point) and **`uv tool install rehuco-agent`** (works for the GUI; native installers / file-association registration are a later polish for wider distribution (§16.8), not needed for the author's own machines).
- **Three packages, not one-package-with-extras.** Extras were considered (`rehuco[node]` / `rehuco[app]`) but rejected for the key reason below: extras are *additive and cannot subtract a base dependency*, so any GUI dependency reachable from the base would still be pulled by `rehuco[node]` — fatal on the TS-230. Separate packages make "the node has no GUI dependencies" **structural rather than carefully-maintained**, and let each package carry its own `requires-python` floor.

## §16.4 The TS-230 / old-glibc constraint: deploy artifacts, don't sync the workspace

The QNAP TS-230 (glibc 2.23) cannot host the agent's PySide6 stack (no compatible wheels). The workspace's single shared `.venv` means `uv sync` at the root tries to install **everything**, including PySide6 — so the workspace itself must never be synced on the TS-230. The resolution rests on a clean separation:

- **The monorepo workspace is the *development* environment; it is not what gets deployed.** Development happens in the full workspace on capable machines (where PySide6 installs fine).
- **Deployment installs individual published packages.** The TS-230 runs `uv tool install rehuco-node` (or installs the built `rehuco-node` wheel into a plain venv) — which pulls `rehuco-node` + `rehuco-core` + server deps and **never references the agent package at all**, because `rehuco-node` doesn't depend on it. The agent isn't "excluded"; it's simply not in the node's dependency tree. The QNAP never sees the workspace.
- **Platform markers on the agent's GUI dependencies** keep even a full workspace lock resolvable in the presence of a platform that can't host them, and prevent accidental installation where they can't go:
  ```toml
  # rehuco-agent/pyproject.toml
  dependencies = [
    "rehuco-core",
    "PySide6; platform_machine != '<ts230-arch>'",   # marker false on the QNAP
    # …other Qt deps similarly gated
  ]
  ```
  (Exact marker keys on whatever uniquely identifies the TS-230 — `platform_machine` for its CPU arch, or `python_version` if it's pinned to an old interpreter.)

- **`rehuco-node` carries its own lower `requires-python`** so it can target the TS-230's older Python independently of the agent's newer floor — something a single-package-with-extras layout could not do (the workspace resolves to the *intersection* of all members' `requires-python`, so the agent's needs would otherwise constrain the node).

## §16.5 TS-230 as a deployment-target canary (continuous compatibility check)

Verifying the node runs on glibc 2.23 is testing the **artifact**, not the workspace:

- **Dev/iteration and the main test suite** run on capable machines: `uv run --package rehuco-node pytest`.
- **A separate, early, recurring step builds `rehuco-node` and installs + smoke-tests it on the actual TS-230** (or a glibc-2.23 container that mimics it), exactly as it will really be installed. This is the dependency canary flagged as a risk in §17.2: if any node dependency (FastAPI, uvicorn, zeroconf, cryptography, pydantic-core, …) lacks a glibc-2.23-compatible wheel, this surfaces it — and it's a *node*-dependency problem to solve (e.g. an older pydantic), entirely independent of the agent's PySide6, which never enters the node's picture. Running this continuously keeps the QNAP-compatibility promise verified rather than discovered late.

> [!NOTE] rehuco-node dependencies
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

- [ ] [#9: feat: container canary + CI workflow for node glibc compatibility](https://github.com/borco/rehuco/issues/9)

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

**Decided: start the monorepo fresh.** Per-repo git history of the old apps isn't valued enough to preserve (the author is comfortable starting clean — "what's another repo"). The old repos (`resource-hub`, `tutcatalog5`, `tutcatalog4`, `pyside_ibo` as a standalone) are kept read-only as an archive/reference, not grafted in. This avoids the `git subtree`/`git-filter-repo` fiddliness entirely. (`pyside_ibo` moves from submodule to a first-class workspace member, §16.2.)

## §16.7 Dependency licensing policy

**Principle: the choice of the final application's license must stay with the author, not be forced by a dependency.** GPL is fine *by deliberate choice* for a final app; being *compelled* into GPL by a linked library is not acceptable — it removes the author's freedom and entangles the reusable libraries (`rehuco-core`, `pyside_ibo`, etc.) that are meant to be independently publishable under whatever license the author picks. (This principle is already evidenced by the author writing an MIT-licensed `pyside6-scintilla` rather than depending on a copyleft alternative.)

Concrete consequence for **docking**:

- **Use `pyqtads` (Qt-Advanced-Docking-System), not KDDockWidgets.** Both are mature and feature-comparable (detach/float/nest/auto-hide/delete-on-close), and KDDockWidgets is in some respects the more capable *framework* (KDAB pedigree, native QML docks, deeper customization). But:
  - **KDDockWidgets is GPL 2.0/3.0** (or paid commercial). Linking it makes the *entire agent* a GPL combined work — cascading into the publish plan (§16.3) and risking entanglement of the reusable libraries. This is a property of the license, not something the binding/packaging can engineer around.
  - **`pyqtads` is permissively licensed (LGPL)** — it can be linked from an app of any license without forcing the app's license — **and ships prebuilt PySide6/PyQt6/PyQt5 bindings on PyPI**, so it drops into the uv workspace as a normal dependency with no build step.
- The packaging objection to KDDockWidgets (no PyPI wheel; bindings must be built from source via shiboken+CMake+libclang) is one the author *could* solve — the same CI-built-binding work already done for `pyside6-scintilla` (shiboken) and `pyside6-lexilla` (nanobind). So bindings are **not** the blocker. **The license is the blocker**, and it is not solvable by effort.
- KDDockWidgets is therefore foreclosed for this project. If the QML-in-`pyqtads` approach (QQuickWidget hosted in a widget dock) proves inadequate, the response is to constrain how QML is used (e.g. keep QML surfaces in non-detachable docks, or reduce the QML footprint) — **not** to switch to KDDockWidgets.

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

Code-signing / notarization is an unpriced prerequisite (§17.2). Auto-update is end-user polish on the same track as §16.8, deferred past the personal critical path (plan: deferred).
