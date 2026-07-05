# §A02. Code Conventions

[[[appendices.code-conventions]]]

## Overview

[[[appendices.code-conventions#overview]]]

Conventions for writing code and docs in this repo, for any contributor — not just Claude Code sessions.
`CLAUDE.md` at the repo root covers how to work with the AI assistant; this page covers how the codebase
itself is written.

## §A02.1 Python

[[[appendices.code-conventions#python]]]

- **Imports:** absolute only (`from rehuco_agent.fields.field import Field`), never relative (`from .field
  import Field`) — grep-able across the monorepo, and safe when code moves between files at different
  package depths.
- **Module filenames:** match their main class (`rehu_document.py` → `RehuDocument`, `field_registry.py` →
  `FieldRegistry`), unless the file deliberately groups several related classes (`properties.py` →
  `TypedProperty`+`SimpleProperty`, `fields/field.py` → `Field`+`FieldBinding`+`FieldModel`).
- **Visibility:** public or private (`__`); no protected (`_`) unless the class is designed for inheritance.
  This holds at module level too — no `_`-prefixed module globals or classes. A helper used by only one
  class belongs inside that class (a `__`-private member, or a public classmethod if it's API — even the
  sentinel-in-signature case works, verified against 3.14's lazy annotations); anything that must stay at
  module level is a plain public name, kept out of the package API by what the package `__init__` exports
  (name mangling doesn't exist outside a class body, so a module-level `_` would be convention-only anyway).
- **Constants:** `Final` without an explicit type when it can be inferred.
- **Naming:** don't bake development-methodology/process labels into identifiers (e.g. a bare `TRACER_`
  prefix naming a constant after "this was built during the tracer-bullet slice") — that context rots once
  the slice ends; put it in a docstring, not the name.
- **Overrides:** `@override` on every method that overrides a base-class method.
- **Docstrings:** Sphinx-style on all functions, including private ones — one-line summary +
  `:param:`/`:returns:`/`:raises:` as needed; no multi-paragraph docstrings for routine code. Closing `"""` on
  its own line for multi-line docstrings, on the same line for single-line ones. Constructor `:param:` entries
  go on the **class** docstring (IDE hover shows them); `__init__` gets no docstring.
- **Comments:** only when the *why* is non-obvious (hidden constraint, subtle invariant, bug workaround). No
  narration of what the code does.
- **Line length:** 120 (ruff enforced).

## §A02.2 PySide6 UI

[[[appendices.code-conventions#pyside-ui]]]

- Window/widget layouts live in `.ui` files, not built up in Python. For a custom widget,
  prefer a `.ui` too, unless it's trivial (simple layout, or the class only overrides/adds
  behavior on an existing widget rather than composing a new layout).
- Collocate a `.ui` with its controller class: `foo_widget.ui`, `foo_widget.py` next to each
  other; the generated `foo_widget_ui.py` is gitignored and rebuilt via `make uis` — never
  hand-edit it.
- A custom widget used inside a `.ui` is placed as a base/`QWidget` placeholder and *promoted*
  to the real class, not embedded as literal custom XML.
- Assets go through `.qrc`. Icons are authored in an Affinity Designer master file and
  exported as `.svg`; `make qrcs` regenerates the gitignored `_rc.py`. A `.ui` referencing a
  qrc-managed resource (e.g. `windowIcon`) must declare
  `<resources><include location="....qrc"/></resources>` so `make uis` emits the matching
  resource import — verify the generated file after adding one.
- Ask before adding a new asset-conversion pipeline (e.g. deriving `.ico` from the `.svg`
  master) rather than improvising one inline.
- Every property/attribute in a `.ui` file must be one Qt Designer's own Property Editor can
  display and edit. Don't hand-add XML that's schema-valid and works at runtime but isn't
  something Designer surfaces — a developer opening the file in Designer needs to be able to
  find and change it there. Anything Designer can't set belongs in the controller class's
  Python code after `setupUi()`, not in the `.ui`.

## §A02.3 Markdown

[[[appendices.code-conventions#markdown]]]

Docs under `docs/` are markdownlint-checked (`.markdownlint.json`; MD013 line length 120, tables exempt). Also:

- Blank lines around headings and lists (MD022/MD032); inside a blockquote the separator is an empty `>` line,
  not a truly blank line.
- Spaced table delimiter rows — `| --- | --- |` — and single-space-padded cells.
- No emphasis-as-heading (MD036) — use real `###` headings.
- Under a spec section heading, list its GitHub issue(s) as task-list items — `- [x] [#N: title](url)` —
  checked when the issue is closed, unchecked while it is open. You may check the box in the same
  change that closes the issue (i.e. tick `- [x]` just before running `gh issue close`), rather than
  waiting for a separate follow-up.

## §A02.4 Testing

[[[appendices.code-conventions#testing]]]

Each test's docstring ends with a `**Test steps:**` bullet list spelling out the steps and checks, so intent
is readable without tracing the code — a project convention, not a pytest feature. The test stack and
how to drive it are covered in [[appendices.testing#qa-gate]].
