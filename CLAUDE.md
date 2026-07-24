# rehuco — Claude Code guidance

## Key documents

Read before any non-trivial task:

- **Design specs:** `docs/specs/` — one topic file per global section range. `docs/specs/README.md` is the
  document map: resolve any `§N.M` reference there, or use the stable `[[doc#slug]]` cross-reference
  convention it defines. Overview (§1–§3) in `docs/specs/architecture-design.md`. Numbers are global and
  renumber-and-shift on insert (no letter suffixes); the map is authoritative.
- **Implementation plan:** `docs/specs/implementation-plan.md` — milestones, tracer-bullet methodology, gates.
- **Code conventions:** [[appendices.code-conventions]] (`docs/specs/appendices/code-conventions.md`) — code,
  PySide6 UI, and Markdown conventions for any contributor (not just Claude Code sessions).

## Repository

- GitHub: <https://github.com/borco/rehuco>
- PyPI names reserved (0.0.0 stubs, 2026-06-29): `rehuco-core`, `rehuco-node`, `rehuco-agent`.

### Labels

- `spike` — throwaway exploration answering one sharp question (keep the lesson, delete the code).
- `pending-cleanup` — work done; issue open only to track a gated teardown (e.g. deleting retained spike code).
  Not `deferred` (that's for work not started).

### Milestones

`Pre-work` (monorepo setup, integration spikes, de-risking), then the feature milestones — **LocalEdit** (local
view/edit), **CacheDB** (cached database), **WatchTutorial** (watch a tutorial), **Borrowing** (offline borrow),
**Swarm** (full multi-node), **Daz3D** (daz3d-personal-database migration) — each sliced `LocalEdit1`,
`LocalEdit2`, …. Audit runs are `X1`, `X2`, …. GH milestone names track the per-slice labels in
`implementation-plan.md`; keep the two in step.

## Monorepo layout

```text
packages/borco-core/      # generic non-GUI utilities — temporary guest, moving out ([[packaging-deployment#three-packages]])
packages/borco-pyside/    # generic PySide widgets/utilities — temporary guest, moving out ([[packaging-deployment#three-packages]])
packages/rehuco-agent/    # PySide6 desktop GUI
packages/rehuco-core/     # shared library: models, .rehu I/O, sync primitives
packages/rehuco-node/     # headless REST node (FastAPI)
```

Root `pyproject.toml` is a **virtual workspace** — no `[project]` table, only `[tool.uv.workspace]`.

## Hardware

The QNAP TS-230 is a **NAS** (SMB share), not a compute host ([[packaging-deployment#ts230-as-nas]]): the node
runs on capable hardware and mounts the share, so the TS-230 imposes no dependency/glibc constraint (canary
findings kept in [[packaging-deployment#glibc-canary]]). Nodes must tolerate the mount being offline
([[mounts-and-storage#offline-mounts]]).

## Tooling

`uv` (workspace + packages), `ruff` (format + lint; replaces black/isort/flake8/pyupgrade), `pyright`
(standard mode; matches Pylance, preferred over mypy for PySide6 + 3.14), `pylint`, `bandit`, `pytest`
(+ `pytest-mock`, `-qt`, `-cov`, `-benchmark`, `-freezer`, `-explicit`), `mkdocs`. VSCode is configured for
ruff formatting/linting; pylint, mypy, and black are disabled there.

Makefile targets: `sync`, `tests`, `cov`, `format`, `bandit`, `pyright`, `pylint`, `check-slugs`,
`qa` (format + check-slugs + cov + bandit + pyright + pylint), `docs-serve`, `publish`, `uis`/`qrcs`/`icons`
(regenerate the gitignored `*_ui.py`/`*_rc.py` and brand-icon exports — run `make uis` after a fresh
checkout/sync), `setup-git`, and the Windows-only dev-launcher targets
`agent-build`/`agent-build-clean`/`agent-register`/`agent-unregister`.

## Model strategy

Default `opusplan` (Opus plans, Sonnet executes). Manually `/model opus` for the reasoning-dense cores listed in
[[implementation-plan#model-strategy]]: sync engine, plugin block save invariant, registry resolution &
serve-after-resync, cross-filesystem safe move.

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
question; keep the lesson, delete the code. The current phase and next slice are deliberately not recorded
here (they'd go stale) — read them off the GH milestones (`gh issue list`) before picking up work.
