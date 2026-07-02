# rehuco — Claude Code guidance

## Key documents

Read before any non-trivial task:

- **Design specs:** `docs/specs/` — one topic file per global section range. `docs/specs/README.md` is the
  **document map**: resolve any `§N.M` reference there. Overview (§1–§3) in `docs/specs/architecture-design.md`.
  Numbers are global and renumber-and-shift on insert (no letter suffixes); the map is authoritative.
- **Implementation plan:** `docs/specs/implementation-plan.md` — milestones, tracer-bullet methodology, gates.

## Repository

- GitHub: <https://github.com/borco/rehuco> (public) · board: <https://github.com/users/borco/projects/5>
- PyPI names reserved (0.0.0 stubs, 2026-06-29): `rehuco-core`, `rehuco-node`, `rehuco-agent`.

### Labels

- `spike` — throwaway exploration answering one sharp question (keep the lesson, delete the code).
- `pending-cleanup` — work done; issue open only to track a gated teardown (e.g. deleting retained spike code).
  Not `deferred` (that's for work not started).

### Milestones

`Pre-work` (monorepo setup, integration spikes, de-risking), then `A0`, `A1`, … — GH milestone names track the
per-slice labels in `implementation-plan.md`; keep the two in step.

## Monorepo layout

```text
apps/rehuco-agent/        # PySide6 desktop GUI
apps/rehuco-node/         # headless REST node (FastAPI)
packages/rehuco-core/     # shared library: models, .rehu I/O, sync primitives
packages/borco-core/      # generic non-GUI utilities — temporary guest, moving out (§16.2)
packages/borco-pyside/    # generic PySide widgets/utilities — temporary guest, moving out (§16.2)
```

Root `pyproject.toml` is a **virtual workspace** — no `[project]` table, only `[tool.uv.workspace]`.

## Hardware

The QNAP TS-230 is a **NAS** (SMB share), not a compute host (§16.4): the node runs on capable hardware and
mounts the share, so the TS-230 imposes no dependency/glibc constraint (canary findings kept in §16.5). Nodes
must tolerate the mount being offline (§9.9).

## Code conventions

- **Visibility:** public or private (`__`); no protected (`_`) unless the class is designed for inheritance.
- **Constants:** `Final` without an explicit type when it can be inferred.
- **Overrides:** `@override` on every method that overrides a base-class method.
- **Docstrings:** Sphinx-style on all functions, including private ones — one-line summary +
  `:param:`/`:returns:`/`:raises:` as needed; no multi-paragraph docstrings for routine code. Closing `"""` on
  its own line for multi-line docstrings, on the same line for single-line ones. Constructor `:param:` entries
  go on the **class** docstring (IDE hover shows them); `__init__` gets no docstring.
- **Comments:** only when the *why* is non-obvious (hidden constraint, subtle invariant, bug workaround). No
  narration of what the code does.
- **Line length:** 120 (ruff enforced).
- **Tests:** end each test docstring with a `**Test steps:**` bullet list spelling out the steps and checks, so
  intent is readable without tracing the code.

## Markdown conventions

Docs under `docs/` are markdownlint-checked (`.markdownlint.json`; MD013 line length 120, tables exempt). Also:

- Blank lines around headings and lists (MD022/MD032); inside a blockquote the separator is an empty `>` line,
  not a truly blank line.
- Spaced table delimiter rows — `| --- | --- |` — and single-space-padded cells.
- No emphasis-as-heading (MD036) — use real `###` headings.
- Under a spec section heading, list its GitHub issue(s) as task-list items — `- [x] [#N: title](url)` —
  checked when closed, unchecked when open.

## Tooling

`uv` (workspace + packages), `ruff` (format + lint; replaces black/isort/flake8/pyupgrade), `pyright`
(standard mode; matches Pylance, preferred over mypy for PySide6 + 3.14), `pylint`, `bandit`, `pytest`
(+ `pytest-mock`, `-qt`, `-cov`, `-benchmark`, `-freezer`, `-explicit`), `mkdocs`. VSCode is configured for
ruff formatting/linting; pylint, mypy, and black are disabled there.

Makefile targets: `sync`, `tests`, `cov`, `format`, `bandit`, `pyright`, `pylint`,
`qa` (format + cov + bandit + pyright + pylint), `docs-serve`.

## Model strategy

Default `opusplan` (Opus plans, Sonnet executes). Manually `/model opus` for the reasoning-dense cores where a
subtle error silently corrupts data: sync engine (§7), plugin block save invariant (§13.2), registry resolution
& serve-after-resync (§6.6, §6.11), cross-filesystem safe move (§9.13).

## Commit and branch policy

- **Never commit or push without explicit user approval** — no auto-commit at task end.
- Feature branches: `issue/NNN/short-slug` (branching from a feature branch is fine); merges always `--no-ff`.
- **Stash unrelated working-tree changes before a `--no-ff` merge**, then pop and commit on top. Committing
  them first buries them beneath the merge commit — and a merge's parents are immutable, so fixing it afterward
  needs reset + re-merge + cherry-pick.
- Message prefixes: type prefixes in use are `repo:`, `config:`, `docs:`, `feat:`, `fix:`, `refactor:`,
  `test:`. On a feature branch, prepend `refs #NNN:` (e.g. `refs #5: docs: record canary result`); commits
  directly on `master` carry no `refs` prefix.

## Development methodology

Agile cadence + tracer-bullet first slices + occasional spikes. **Tracer bullet** — minimal but real,
production-grade, kept; proves the layers connect end-to-end. **Spike** — throwaway; answers one sharp
question; keep the lesson, delete the code. Current phase: **Pre-work**. Next milestone: **A0** — double-click
a `.rehu` → single-instance agent → read → render common fields + Markdown + image strip → edit one field →
atomic-save.
