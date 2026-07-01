# rehuco — Claude Code guidance

## Key documents

- **Design specs:** `docs/specs/` — the design is split across topic files, one per
  section range. `docs/specs/README.md` is the **document map** (which `§N` lives in which
  file) and records the section-numbering convention. Start at
  `docs/specs/architecture-design.md` for the high-level overview (§1–§3).
- **Implementation plan:** `docs/specs/implementation-plan.md` — milestone breakdown, tracer-bullet
  methodology, sequencing gates, honest caveats.

Read both before any non-trivial task. Section references use global numbers in the form
§N.M; resolve any number to its file via `docs/specs/README.md`. Numbers are global and may
be renumbered on insert (no letter suffixes) — see the convention in that README.

## Repository

- **GitHub:** <https://github.com/borco/rehuco> (public)
- **Project board:** <https://github.com/users/borco/projects/5>
- **PyPI names reserved** (0.0.0 stub packages published 2026-06-29):
  - <https://pypi.org/project/rehuco-core/>
  - <https://pypi.org/project/rehuco-node/>
  - <https://pypi.org/project/rehuco-agent/>

## GitHub labels and milestones

Issues live on the [project board](https://github.com/users/borco/projects/5). Keep these
consistent as new ones are added:

### Labels

- `spike` — throwaway exploration answering one sharp technical question (keep the lesson,
  delete the code; see *Development methodology* below).

### Milestones

- `Pre-work` — monorepo setup, integration spikes, and de-risking done before/around the
  first tracer-bullet slice.

## Monorepo layout

```text
apps/rehuco-agent/        # PySide6 desktop GUI
apps/rehuco-node/         # headless REST node (FastAPI)
packages/rehuco-core/     # shared library: models, .rehu I/O, sync primitives
```

Root `pyproject.toml` is a **virtual workspace** — no `[project]` table, only
`[tool.uv.workspace]`.

## Hardware compatibility

The QNAP TS-230 is the lowest-spec *target* (not a hard requirement). `rehuco-node`'s
`requires-python` floor and dependency choices are kept compatible with it where possible.

## Code conventions

### Visibility

Public or private (`__`). No protected (`_`) unless the class is explicitly designed for
inheritance. This makes the public API unambiguous.

### Constants

`Final` without an explicit type when the type can be inferred.

### Overrides

`@override` on every method that overrides a base-class method.

### Docstrings

Sphinx-style on all functions, including private ones.
One-line summary + `:param:` / `:returns:` / `:raises:` as needed.
No multi-paragraph docstrings or multi-line comment blocks for routine code.

- **Closing `"""` placement** — on its own line for a multi-line docstring; on the same
  line as the text for a single-line docstring.
- **Constructor args live in the class docstring**, not in `__init__`. Put the `:param:`
  entries on the class so IDE hover over the class name shows them; `__init__` gets no
  docstring of its own.

### Comments

Only when the *why* is non-obvious: hidden constraint, subtle invariant, bug workaround,
surprising behavior. No narration of what the code does.

### Line length

120 characters (ruff enforced).

### Tests

End each test's docstring with a **Test steps:** bullet list spelling out the steps and
checks the test performs, so its intent is readable without tracing the code:

```python
"""One-line summary of what is verified.

**Test steps:**

* launch a primary app instance
* launch a second instance with mocked argv
* verify the primary receives the second instance's arguments
"""
```

## Markdown conventions

Docs under `docs/` are markdownlint-checked (`.markdownlint.json` sets MD013 line length 120,
tables exempt). Beyond that:

- **Headings and lists are surrounded by blank lines** (MD022/MD032).
- **Inside a blockquote, the separating blank line must itself be a quote line** — write an
  empty `>` (i.e. add a `>\n` line), not a truly blank line, or the list/paragraph isn't
  separated within the quote.
- **Table delimiter rows are spaced** — `| --- | --- |`, not `|---|---|` (header and data
  cells padded with single spaces too).
- **No emphasis-as-heading** (MD036) — use real `###` headings, not bold text.
- **Issue links under spec section headings** — when a section has a corresponding GitHub issue, list it
  immediately below the heading as a task-list item. Closed issues are checked; open ones are unchecked.
  Use `[#N: title](url)` so the number is scannable and the title gives context. Multiple issues can be listed.

  ```markdown
  - [x] [#5: spike: QNAP/glibc dependency canary](https://github.com/borco/rehuco/issues/5)
  ```

## Tooling

| Tool | Role |
| --- | --- |
| `uv` | workspace + package manager |
| `ruff` | formatter + linter (replaces black, isort, flake8, pyupgrade) |
| `pyright` | type checker (standard mode; matches Pylance in VS Code — preferred over mypy for PySide6 + Python 3.14) |
| `pylint` | static analysis |
| `bandit` | security scanning |
| `pytest` | test runner |
| `pytest-mock` | mocking |
| `pytest-qt` | Qt widget / event-loop testing |
| `pytest-cov` | coverage |
| `pytest-benchmark` | benchmarking |
| `pytest-freezer` | time freezing |
| `pytest-explicit` | explicit test markers |
| `mkdocs` | documentation site |

VSCode workspace is configured to use ruff for formatting and linting. pylint, mypy, and black are
disabled in favour of ruff / pyright.

## Makefile targets

| Target | Action |
| --- | --- |
| `make sync` | install all workspace packages in dev mode |
| `make tests` | run pytest |
| `make cov` | run pytest with branch coverage report |
| `make format` | run ruff format + ruff check --fix |
| `make bandit` | run bandit security scanner |
| `make pyright` | run pyright type checker (standard mode) |
| `make pylint` | run pylint |
| `make qa` | format + cov + bandit + pyright + pylint |
| `make docs-serve` | serve mkdocs locally |

## Model strategy

Use `opusplan` as the default (Opus for plan mode, Sonnet for execution).

**Manually switch to Opus (`/model opus`) for these specific sections** — they are
reasoning-dense and a subtle error silently corrupts data:

- **Sync engine** — version vector, activity log, conflict/merge, tombstones (§7).
- **Plugin block save invariant** — live/inert/claim-then-abandon rule (§13.2).
- **Registry resolution & serve-after-resync** — preferred-authority, chatter, version-marker
  comparison (§6.6, §6.11).
- **Cross-filesystem safe move** — checksum-gated, data-loss-sensitive (§9.13).

## Commit and branch policy

**Always wait for explicit user approval before committing or pushing.** Do not commit
automatically at the end of a task.

Work is done on feature branches named `issue/NNN/some-short-slug` (e.g.
`issue/42/add-field-toolkit`), where NNN is the GitHub issue number. Branching from a
feature branch is fine. Merges always use `--no-ff`.

Commit type prefixes in use: `repo:`, `config:`, `docs:`, `feat:`, `fix:`, `refactor:`, `test:`.

When committing on a feature branch (`issue/NNN/...`), prefix the message with `refs #NNN:` before the type prefix.
Commits directly on `master` carry no prefix.

```text
refs #5: docs: record QNAP/glibc canary result in §16.5.1
```

## Development methodology

Agile cadence + tracer-bullet first slices + occasional spikes.

- **Tracer bullet** — minimal but real, production-grade, kept. Proves layers connect end-to-end.
- **Spike** — throwaway, answers one sharp technical question. Delete after; keep only the lesson.

Current phase: **Pre-work** (monorepo setup, pyqtads+QML integration spike, QNAP glibc canary).
Next milestone: **A0** — double-click a `.rehu` → single-instance agent opens → reads file →
renders common fields + Markdown + image strip → edit one field → atomic-save back.
