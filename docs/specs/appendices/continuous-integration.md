# Continuous Integration — Design Decisions and Hurdles

[[[appendices.continuous-integration]]]

## Overview

[[[appendices.continuous-integration#overview]]]

Why the cross-platform CI workflow ([#14](https://github.com/borco/rehuco/issues/14)) isn't just
`make qa` wrapped in a GitHub Actions matrix, and the toolchain gaps it had to work around. Builds
on the cross-platform QA groundwork in [[appendices.testing#overview]] (issue
[#15](https://github.com/borco/rehuco/issues/15)).

## 1. `make qa` mutates sources — CI needs a non-mutating equivalent

[[[appendices.continuous-integration#non-mutating-ci]]]

`make format` — the first step of `make qa` — runs `ruff format .` then `ruff check --fix .`. Both
rewrite files in place. Running `make qa` verbatim in CI would silently reformat and autofix a PR's
ephemeral checkout and then report green even though the PR branch itself is unformatted or
lint-broken — the opposite of what a gate is for.

The workflow instead runs the non-mutating equivalents directly: `ruff format --check .` and
`ruff check .` (no `--fix`), followed by the other `make qa` steps unchanged — `make cov`, `make
bandit`, `make pyright`, `make pylint` — since none of those mutate sources.

## 2. The Qt build artifacts aren't distributed — CI has to generate them, like any dev checkout

[[[appendices.continuous-integration#ci-must-build-qt]]]

`viewer_window_ui.py`, `main_rc.py`, and `rehuco-agent.ico` are gitignored, not committed: per
[[appendices.testing#qualified-rc-imports]], `rehuco-agent` doesn't work without them, but they don't ship in the repo,
so `make uis`
(which pulls in `qrcs` and `icons`) has to run before `pytest` can even collect tests — on every
matrix leg, since a CI checkout starts from the same source tree as a fresh clone.

Every runner turned out to be missing at least one tool for that. Confirmed by the first real run
of this workflow (not just the `actions/runner-images` docs): `ubuntu-latest` and `macos-latest`
have no ImageMagick preinstalled at all — `make: magick: No such file or directory` — so both need
an explicit install (`apt-get install imagemagick` / `brew install imagemagick`). Ubuntu's
`imagemagick` apt package resolves to `imagemagick-6.q16` — ImageMagick 6, which has no unified
`magick` binary at all (that command is IM7-only); the Linux step installs it, then symlinks IM6's
`convert` to `magick` if the real one isn't present, since `convert` accepts the same flags the
Makefile's icon rule uses. `windows-latest` is the opposite case: it ships ImageMagick but has **no
GNU Make** and **no Scoop** (checked
against the `actions/runner-images` Windows2022 readme ahead of time, since Chocolatey vs. Scoop
was a real design choice, not just a gap to fill in reactively). Two alternatives to installing
`make` there were rejected:

- **Bootstrap Scoop** (the package manager `apps/rehuco-agent/launcher/README.md` recommends for a
  developer's own machine) — it isn't present on the runner and would need its own
  install-and-trust step before it could install anything, unlike Chocolatey which is ready to use.
- **Hand-duplicate the `uic`/`rcc`/`magick` invocations in the workflow YAML** — this would
  re-derive the OS-native `--python-paths` separator logic (`;` on Windows, `:` elsewhere) that the
  Makefile already got right for issue #15, creating a second place for that fix to drift out of
  sync.

The workflow instead adds one per-OS package-manager step per missing tool (ImageMagick on
Linux/macOS, `make` on Windows) and then runs `make uis` unchanged on all three platforms, keeping
the Makefile as the single source of truth for codegen. The Windows leg was the bigger unknown
going in — `choco`-installed `make` driving the Makefile's `$(shell find ...)` codegen through Git
Bash's coreutils, a combination never exercised in this repo before — and it passed on the first
real run; the ImageMagick gap on the other two legs was the one this section's first draft missed
by trusting the `actions/runner-images` docs for Windows without checking Linux/macOS too.

One cosmetic follow-up on the macOS leg: the runner image pre-taps `aws/tap`, and newer Homebrew
prints a tap-trust warning that it's ignoring the untrusted tap on every `brew install`. The QA
job only needs the `homebrew/core` `imagemagick` formula, so the macOS step runs `brew untap
aws/tap` first (guarded, since the tap may be absent on a future image) to keep the install output
free of that warning annotation.

## 3. Bare Linux runners are missing Qt runtime libraries, not just a display

[[[appendices.continuous-integration#missing-qt-libs]]]

Past `make uis`, `ubuntu-latest` failed again, differently: `pytest` itself crashed with
`INTERNALERROR> ImportError: libEGL.so.1: cannot open shared object file` while `pytest-qt`
imported `PySide6.QtGui`. This is unrelated to [[appendices.testing#headless-qt]]'s `QT_QPA_PLATFORM=offscreen` — that
setting
only picks *which* Qt platform plugin loads once `QtGui` is already importable; it doesn't change
what shared libraries `QtGui` itself links against at import time. A bare `ubuntu-latest` runner
ships none of them (macOS and Windows have no equivalent gap, so only the Linux leg needs this).

Installing just `libegl1` got `pytest` past that import — but the run then segfaulted (`Error
139`) inside `QLocalServer`/`QLocalSocket` teardown in the `ApplicationSingleton` test. The Linux
leg installs the fuller `libgl1 libegl1 libxkbcommon0` set the sibling `pyside6-scintilla` project
uses for the same PySide6-pytest-`offscreen` combination: it's an already-proven runtime-lib
baseline and keeps the `QtGui` import robust across runner-image changes. A community GitHub Action,
`tlambert03/setup-qt-libs`, was also checked as a candidate — but its package list (`libdbus-1-3`,
six `libxcb-*` packages, `x11-utils`, `libopengl0`, deprecated in favor of
`pyvista/setup-headless-display-action`) targets the **xcb** platform plugin, not `offscreen`, and
adding a third-party action's broader surface for packages this project's own Qt/pytest combination
doesn't need wasn't worth it. `pyside6-scintilla`'s narrower, already-proven set was adopted instead.

That segfault turned out to be a **separate problem from the missing libraries**, and adding the
fuller Qt-lib set did *not* eliminate it: it reproduced identically on a WSL Ubuntu 24.04 box that
already had all three libraries present. The real cause is a deferred-`deleteLater()` teardown
ordering bug in the *test harness*, not a runtime-lib or a workflow gap — the crash signature
[[appendices.testing#headless-qt]] documents was never fully closed by `QT_QPA_PLATFORM=offscreen` on Linux. The fix
lives in
the `make_singleton` fixture (an explicit `DeferredDelete` flush at teardown); see [[appendices.testing#headless-qt]]
for the
mechanism. No CI-config change was needed for it beyond the library installs already described.

## 4. One shell for all three runners

[[[appendices.continuous-integration#cross-platform-shell]]]

The job sets `defaults.run.shell: bash`. On `windows-latest` this resolves to the
Git-for-Windows-backed bash that GitHub Actions already provides there, which bundles the GNU
coreutils (`find`, `sed`, `tr`) the Makefile's `$(shell find apps packages -maxdepth 3 -name src
-type d ...)` codegen calls need. Without it, `make`'s recipe lines and `$(shell ...)` calls would
run under whatever shell each OS defaults to (`pwsh` on Windows), which doesn't have those
utilities — so every step is written once, not branched per OS.

## 5. Pinning the Python version explicitly

[[[appendices.continuous-integration#pin-python]]]

Every package pins `requires-python = ">=3.14"`, which leaves the exact minor/patch version up to
whatever a given runner image resolves it to. `astral-sh/setup-uv`'s `python-version: "3.14"` input
overrides that and pins the version `uv` provisions, guaranteeing it matches what `ruff`'s
`target-version = "py314"` and `pyright`'s `pythonVersion = "3.14"` assume.

## 6. Pinning `astral-sh/setup-uv` to an immutable release, not a floating major tag

[[[appendices.continuous-integration#fix-node20-warning]]]

GitHub flagged `astral-sh/setup-uv@v6` as deprecated: it declares `node20`, which Actions is
retiring, and was silently being run under `node24` anyway. `v7`+ declare `node24`, but
`astral-sh/setup-uv`'s own v8.0.0 release notes announce it **stopped publishing floating major/minor
tags** (`@v8`, `@v8.0`) specifically to close the supply-chain risk floating tags create — the same
class of attack as the 2025 `tj-actions` compromise, where a floating tag got repointed to
malicious code. Pinned to `@v8.2.0` (the immutable per-release tag) in both this workflow and
`publish-docs.yml`, rather than following `actions/checkout`'s convention of a floating `@v7`.
`actions/checkout@v7` and `docker/setup-qemu-action@v4` (`canary-rehuco-node.yml`) already resolve
to `node24` as floating tags, so neither needed a change.

## 7. Two things that needed no extra work

[[[appendices.continuous-integration#no-extra-work]]]

- **Headless Qt.** `QT_QPA_PLATFORM=offscreen` needs no workflow-level setting — the repo-root
  `conftest.py` already sets it ([[appendices.testing#headless-qt]]) before any test module can build a `QApplication`.
- **`fail-fast: false`.** Deliberate, not a default left alone: without it, the first matrix leg to
  fail cancels the other two, hiding whether a failure is OS-specific or universal — defeating the
  point of running the matrix at all.

## 8. Per-OS coverage reporting (Codecov)

[[[appendices.continuous-integration#per-os-coverage]]]

`make cov` only ever printed `term-missing` to the job log — nothing was uploaded anywhere, so the
README's per-OS coverage badges ([#19](https://github.com/borco/rehuco/issues/19)) had no live data
source. Getting them working needed both account-side setup outside this repo and two workflow-side
changes.

**Account setup (not git-tracked):** sign up at codecov.io with GitHub OAuth, activate
`borco/rehuco` in the Codecov dashboard (installs their GitHub App for it), copy the repo's
upload token from its Codecov settings page, and store it as the `CODECOV_TOKEN` secret under
`borco/rehuco` → Settings → Secrets and variables → Actions. Public repos can technically upload
tokenless, but recent `codecov-action` versions have been unreliable (rate-limited) without one, so
the token was set up regardless rather than relying on that path.

**`Makefile`:** the `cov` target gained `--cov-report=xml` alongside the existing
`--cov-report=term-missing` — pytest-cov accepts multiple `--cov-report` flags in one invocation, so
one target still serves both local dev (reads the terminal summary) and CI (uploads the XML), no
separate CI-only target needed.

**`qa.yml`:** the matrix moved from a flat `os: [...]` list to `include: [{os, flag}, ...]`, adding
a lowercase `flag` value per leg (`linux`/`macos`/`windows`). `runner.os` itself resolves to
`Linux`/`macOS`/`Windows` (mixed case), and Codecov flag names are conventionally lowercase;
computing the mapping once in the matrix avoided a per-step case-conversion. A
`codecov/codecov-action@v5` step runs right after `make cov`, authenticated via `CODECOV_TOKEN` and
tagged with `flags: ${{ matrix.flag }}` so Codecov keeps the three OS coverage numbers (and badges)
separate instead of blending them. It runs with `fail_ci_if_error: false` deliberately: this is
new, unverified plumbing, and an upload hiccup on a reporting side-channel shouldn't fail the whole
QA gate — worth revisiting once it's proven reliable across a few runs.
