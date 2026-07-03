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

Windows turned out to be the one leg missing a tool for that: checking the
`actions/runner-images` Windows2022 image, it ships ImageMagick preinstalled (so `magick` needs no
extra install) and has Chocolatey preinstalled, but has **no GNU Make** and **no Scoop**. Two
alternatives were rejected:

- **Bootstrap Scoop** (the package manager `apps/rehuco-agent/launcher/README.md` recommends for a
  developer's own machine) — it isn't present on the runner and would need its own
  install-and-trust step before it could install anything, unlike Chocolatey which is ready to use.
- **Hand-duplicate the `uic`/`rcc`/`magick` invocations in the workflow YAML** — this would
  re-derive the OS-native `--python-paths` separator logic (`;` on Windows, `:` elsewhere) that the
  Makefile already got right for issue #15, creating a second place for that fix to drift out of
  sync.

The workflow instead adds a Windows-only `choco install make` step and then runs `make uis`
unchanged on all three platforms, keeping the Makefile as the single source of truth for codegen.
This is the one combination in the whole workflow that hadn't been exercised anywhere in this repo
before — `choco`-installed `make` driving the Makefile's `$(shell find ...)` codegen under
Windows — and may need a follow-up fix once the first real CI run confirms it.

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
