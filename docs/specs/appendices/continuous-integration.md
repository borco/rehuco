# §A02. Continuous Integration — Design Decisions and Hurdles

Why the cross-platform CI workflow ([#14](https://github.com/borco/rehuco/issues/14)) isn't just
`make qa` wrapped in a GitHub Actions matrix, and the toolchain gaps it had to work around. Builds
on the cross-platform QA groundwork in §A04 (issue [#15](https://github.com/borco/rehuco/issues/15)).

## §A02.1 `make qa` mutates sources — CI needs a non-mutating equivalent

`make format` — the first step of `make qa` — runs `ruff format .` then `ruff check --fix .`. Both
rewrite files in place. Running `make qa` verbatim in CI would silently reformat and autofix a PR's
ephemeral checkout and then report green even though the PR branch itself is unformatted or
lint-broken — the opposite of what a gate is for.

The workflow instead runs the non-mutating equivalents directly: `ruff format --check .` and
`ruff check .` (no `--fix`), followed by the other `make qa` steps unchanged — `make cov`, `make
bandit`, `make pyright`, `make pylint` — since none of those mutate sources.

## §A02.2 The Qt build artifacts aren't distributed — CI has to generate them, like any dev checkout

`viewer_window_ui.py`, `main_rc.py`, and `rehuco-agent.ico` are gitignored, not committed: per
§A04.6, `rehuco-agent` doesn't work without them, but they don't ship in the repo, so `make uis`
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

## §A02.3 One shell for all three runners

The job sets `defaults.run.shell: bash`. On `windows-latest` this resolves to the
Git-for-Windows-backed bash that GitHub Actions already provides there, which bundles the GNU
coreutils (`find`, `sed`, `tr`) the Makefile's `$(shell find apps packages -maxdepth 3 -name src
-type d ...)` codegen calls need. Without it, `make`'s recipe lines and `$(shell ...)` calls would
run under whatever shell each OS defaults to (`pwsh` on Windows), which doesn't have those
utilities — so every step is written once, not branched per OS.

## §A02.4 Pinning the Python version explicitly

Every package pins `requires-python = ">=3.14"`, which leaves the exact minor/patch version up to
whatever a given runner image resolves it to. `astral-sh/setup-uv`'s `python-version: "3.14"` input
overrides that and pins the version `uv` provisions, guaranteeing it matches what `ruff`'s
`target-version = "py314"` and `pyright`'s `pythonVersion = "3.14"` assume.

## §A02.5 Two things that needed no extra work

- **Headless Qt.** `QT_QPA_PLATFORM=offscreen` needs no workflow-level setting — the repo-root
  `conftest.py` already sets it (§A04.2) before any test module can build a `QApplication`.
- **`fail-fast: false`.** Deliberate, not a default left alone: without it, the first matrix leg to
  fail cancels the other two, hiding whether a failure is OS-specific or universal — defeating the
  point of running the matrix at all.
