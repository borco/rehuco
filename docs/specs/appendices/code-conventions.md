# Code Conventions

[[[appendices.code-conventions]]]

## Overview

[[[appendices.code-conventions#overview]]]

Conventions for writing code and docs in this repo, for any contributor — not just Claude Code sessions.
`CLAUDE.md` at the repo root covers how to work with the AI assistant; this page covers how the codebase
itself is written.

## 1. Python

[[[appendices.code-conventions#python]]]

- **Imports:** **relative within a package's library code** (`from .field import Field`); **absolute** only in
  tests and the app's entry file (`from rehuco_agent.fields.field import Field`). Relative keeps intra-package
  imports stable when a package is published or moved between depths. The codebase is mid-migration to this rule;
  the `rehuco-core` sweep is a follow-up.
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
- **Size caps:** a source module past a pylint cap splits along a cohesive seam (`RootsChecksumVerbs`,
  `RootsRowActions`), never by inlining or a pragma; a pragma is right only for a module that is one cohesive thing
  (`CatalogCache`), and says why. `too-many-locals` is cured by a helper. A test module past 1000 lines is split,
  importing helpers from its sibling (#457, #458, #469, #395).

## 2. PySide6 UI

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
- Name widgets in `.ui` files `snake_case`, not Qt Designer's default `camelCase` — this is a
  recommendation, not a hard rule; use `camelCase` where justified (e.g. overriding a name Qt
  itself expects). A widget name that's already a single dictionary word a spell checker
  recognizes (`checkbox`, `toolbar`) doesn't need splitting; a compound default that isn't a
  real single word (`centralwidget`, `statusbar`, `menubar`) becomes `central_widget`,
  `status_bar`, `menu_bar`.

### Command surfaces

[[[appendices.code-conventions#command-surfaces]]]

A command can be reached from several places; each has one job.

- **The menu bar is the complete index.** Every command is in a menu, whatever else shows it, so a command is
  findable without knowing which widget owns it.
- **A button goes at the narrowest widget containing everything it affects.** *Scan* affects every browser of a
  catalog, so it is on the catalog shell's toolbar; *Add Root* and *Remove Root* affect only the Roots view, so
  they are on its sub-dock's title bar (`CDockWidget.setTitleBarActions`). A command on one item — a root, a row —
  goes on that item's context menu.
- **A sub-dock earns a toolbar only past about three frequent actions.** Up to that, its title-bar actions are
  enough.
- **One `QAction` serves every surface**, so enabled state, text and shortcut are decided once, by the widget
  that owns it.

### Worker threads

[[[appendices.code-conventions#worker-threads]]]

Two kinds of background work, two kinds of thread. The reasoning, and the measurements behind it, are in the module
docstring of `borco_core.path_presence` — read it there, where the code is.

- **Bounded work whose answer goes back to a widget runs on a `QThreadPool`** (`QThreadPool.globalInstance()`, a
  `QRunnable` posting its answer, judged on the GUI thread so a stale one is dropped — [[appendices.task-queue#serial]]
  explains why the task queue is not one). This is the default, and nearly all of the agent's background work.
- **Work that can block on storage or a network the app does not control, and so must never hold up quitting, runs on
  a Python `threading.Thread(daemon=True)`** with a `threading.Event` to stop it. Qt joins its pools at exit, so a
  worker stuck in a call to a switched-off server keeps the process alive for as long as the call takes (21 s measured
  for an SMB host); a daemon thread is simply left behind. Nothing is killed: `QThread.terminate()` is unsafe, and a
  `QThread` destroyed while running aborts the process.
- **A pool job never lets a reader's exception escape** (#480): the pool swallows it and no answer ever arrives.
  Catch broadly with a reasoned pragma, log it, and answer *unreadable*.
- **A worker holds the GIL inside every Qt call PySide does not release it for, so it never makes one that can take a
  signal-slot mutex** (#529). A `QImageReader` left to find its format asks every plugin to look at the bytes, and
  the SVG plugin's look connects a signal, so a reader on a pool thread is a `format_reader`, told its format up front
  with detection off. **So no `QMediaPlayer` on a worker** (#522): PySide releases the GIL only for `setSource` and
  the event loop, and holds it across the constructor, `connect` and the destructor, each of which takes a signal-slot
  mutex; a player has to live on the GUI thread, which is what made a Qt Multimedia duration probe not worth its keep
  ([[appendices.post-mortem#ui-and-deployment]]).
- **A `QObject` gets a parent, usually `self`, or an explicit delete** (#529). One held only in an attribute, once in
  a reference cycle, is destroyed by the cyclic collector on whichever thread allocates next, and on a pool thread
  `~QObject` takes a signal-slot mutex and then waits for the GIL the GUI thread may hold. With no natural parent,
  the owner deletes it when done (`FieldsForm.delete_later`, `LogBridge.close`, `ScraperExecutor.shutdown`); a test
  hands what it builds bare to the `delete_at_teardown` fixture.
- **Work that runs again and again reports through one `QObject` its caller owns, never one per run** (#529): a
  per-run child stays on its parent until the parent goes — a leak in an app that runs for days, on a node for
  weeks — and deleting each after it relayed proved fragile. `ScrapeJob.Relay` carries every job's outcome with the
  job as its first argument; a page reuses one `PersonaAction`; a measurement's runner is its row's child.
- **A daemon thread holds no Qt object and delivers nothing after `stop()`.** Its callback runs on its own thread and
  only emits a signal, which Qt queues to the GUI thread; the owner stops it first thing when the window closes.
- **Building many objects on a worker pauses the cyclic collector** (#455, #500) — and only for that build, never
  `gc.freeze()`.
- First users: the task queue's worker ([[appendices.task-queue#teardown]], daemon for the same reason) and
  `borco_core.PresenceScan` (#464).

### Qt and PySide behaviour

[[[appendices.code-conventions#qt-behaviour]]]

Facts about Qt and PySide that cost time to find, beyond the thread rules above. QtAds' own are in
[[appendices.qt-ads]]; driving these in tests, in [[appendices.testing#offscreen-qt]].

- **Never keep the wrapper of an object Qt owns when its parent can hand it back** (#459, #488): read it per use; delete
  a child menu in a `finally` around `exec`; walk a widget's own descendants, not `nextInFocusChain()` (#487).
- **Deletion** (#529, #479): a queued signal to a Python callable posts to PySide's receiver — make the sender its own
  (`LogBridge.Marshaller`); a deleted `QObject`'s signals and methods raise `RuntimeError`; a `QObject` kept alive only
  by its children's closures deletes itself mid-destruction; `destroyed` fires parent first — closures hold a token. A
  form keeping strong references to the widgets its grids own leaves the model's receivers doubled after a teardown
  (`test_a_teardown_lets_go_of_every_model_connection`): hold `weakref.ref` (#568). A host-parented `QAction` a
  document's sub-docks make is deleted in their `teardown`, or a preview leaks one per document switch (#505).
- **Signals**: a signal-blocked `setText` hides the clear button, which emits `textEdited` — a debounce connects
  `textChanged` (#406); pressing a `QToolButton` in a QtAds dock moves the focus to the dock's scroll area, so a field's
  `editingFinished` fires before the button's action — a test patching `hasFocus` hides it (#514); trace real
  connection order (#376); state kept by a signal is as reliable as its quietest listener — compute at paint time
  (#304, #457); a `focusChanged` connection outlives its widget (#387).
- **Rows**: filtering the current row out of a proxy drops the current index (#344); Qt moves it inside
  `rowsAboutToBeRemoved` — defer with `QTimer.singleShot(0, self, ...)` (#387).
- **Sizing**: never from geometry before the first layout — `sizeHint()` (#377); a pane's minimum width must not follow
  its content (#457); `isHidden()` is the widget's own flag — `isVisibleTo(ancestor)` (#458); a widget made after its
  parent was shown stays hidden until `show()`; an unshown `ElidedLabel` reads `…` (#378).
- **Widgets**: `QColumnView` — `createColumn` for a delegate, `setFixedWidth(0)` for the preview (#378); a `QToolButton`
  mirrors its action but not its font; a `StrEnum` item comes back `str`; `applicationDisplayName()` falls back to
  `applicationName()` (#412); `QStatusBar.addPermanentWidget` appends rightwards; `QTimer.singleShot(ms, receiver,
  callable)` did not fire in tests — use a member `QTimer` (#506); `CDockManager` works under a plain widget (#498). A
  row removed from a layout and `deleteLater`-ed is gone by the next wait — test `shiboken6.isValid`, not
  `isVisible` (#505).
- **Menus**: a `QWidgetAction` row owns its columns — raise `maxIconWidth` (#465); an `aboutToShow` tail keeps one
  `QActionGroup` (#402); a card list marks its current card by its buttons alone (#463).
- **Drag routing** (#387, #461, #485): a drag belongs to the widget that accepted its enter; a disabled widget gets
  none; an *ignored* enter hands the drag to the nearest accepting ancestor, so a filter that ignores a link passes it
  on and forwarding by hand delivers it twice (#567); a test link carries its `text/plain` too, or a `QLineEdit`
  declines it anyway; browsers end UTF-16 `text/x-moz-url` with a NUL; a `QListView` reorder
  ([[appendices.testing#offscreen-qt]]).
- **A custom delegate on Windows** (#383): editor on `option.rect`; nothing painted under it; `HighlightedText`.
- **`SimpleProperty` keeps `name` as `_Class__name`** (#497): a private method `__name` on the same class silently
  takes its place — the banner read a bound method as its text.
- **Settings blocks** (#508): exact `QFrame` direct children in child order; a platform's blocks are `QObject`
  controllers `setParent`ed before `setupUi`, then `insertWidget`ed first.
- **Dialog traps** (#416): `.ui` `QTableWidget` headers fail pyright; `QDialogButtonBox` orders by role; `ScintillaEdit`
  eats Esc and shadows `setFocus`. A floating QtAds container ignores close — quit on an accepted close (#507).
- **Glyphs**: the Phosphor fonts name their glyphs `uniXXXX` only — render a codepoint to check it (#505: `\ue30c` is
  the magnifier).

## 3. Markdown

[[[appendices.code-conventions#markdown]]]

Docs under `docs/` are markdownlint-checked (`.markdownlint.json`; MD013 line length 120, tables exempt). Also:

- Blank lines around headings and lists (MD022/MD032); inside a blockquote the separator is an empty `>` line,
  not a truly blank line.
- Spaced table delimiter rows — `| --- | --- |` — and single-space-padded cells.
- No emphasis-as-heading (MD036) — use real `###` headings.
- **By hand**: no wrapped line starts with `#NNN` — markdownlint reads it as a heading (MD018); `awk 'length>120'`
  over-counts lines with em dashes, so measure in characters; compare markdownlint's findings with `git show
  HEAD:file` first, so only new ones are yours.
- Under a spec section heading, list its GitHub issue(s) as plain list items — `- [#N: title](url)` —
  regardless of whether the issue is open or closed. Deliberately **not** a `- [ ]`/`- [x]` task list:
  a checkbox has to be ticked in a commit every time an issue closes, which is churn in the specs for
  state GitHub already tracks authoritatively. The link records *which* issues a section belongs to;
  their status is read on GitHub.
- **Cross-renderer link rendering.** Docs are read both on GitHub (blob view, PRs) and the published
  mkdocs site, which render some references differently:
  - A bare `#123` issue/PR reference autolinks natively on GitHub already; `pymdownx.magiclink`
    (`mkdocs.yml`) gives it the same treatment on the published site. Its issue-shorthand pattern
    requires digits right after `#`, so it never collides with a `[[doc#slug]]` cross-reference
    token (slug segments are never all-digit) — see "Symbolic cross-references" in
    [`docs/specs/README.md`](../README.md).
  - A plain relative link from a doc into a repo file outside `docs/` (e.g. a `.py` source file
    under `packages/`) resolves natively on GitHub, but 404s on the built mkdocs site,
    since only `docs/` is ever published. Write such links as plain relative paths regardless —
    `tools/mkdocs_relative_link_hook.py` rewrites, at build time only, any link whose target falls
      outside `docs_dir` to an absolute `{repo_url}/blob/{branch}/...` link; GitHub needs no change.

## 4. Testing

[[[appendices.code-conventions#testing]]]

Each test's docstring ends with a `**Test steps:**` bullet list spelling out the steps and checks, so intent
is readable without tracing the code — a project convention, not a pytest feature. The test stack and
how to drive it are covered in [[appendices.testing#qa-gate]].
