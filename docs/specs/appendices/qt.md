# Qt — Reporting Bugs Upstream

[[[appendices.qt]]]

## Overview

[[[appendices.qt#overview]]]

How a Qt or PySide6 bug found here becomes a report on [bugreports.qt.io](https://bugreports.qt.io): what to write,
how to write it so it is read, and what to do once it is posted. The first report made this way was PYSIDE-3511
(#651); `qt-repros/qimagereader_getter_keeps_gil.py` and its `.md`, beside the work queue, are the worked example,
with #652's `collected_qobject_takes_gil_under_mutex` pair.

## 1. Two files per report

[[[appendices.qt#two-files]]]

Each report is a pair in `qt-repros/` beside the work queue, outside every checkout:

- **`<name>.py`**: a self-contained reproducer. One file, PySide6 only, its dependencies in a PEP 723 `# /// script`
  block (`requires-python`, `PySide6-Essentials`), run by `uv run <name>.py`. It is attached to the Qt report.
- **`<name>.md`**: how to fill the Jira form, field by field ([[appendices.qt#jira-form]]). The owner posts; nothing
  is filed from a session.

## 2. The reproducer is ordinary, supported Qt code

[[[appendices.qt#qt-way]]]

A Qt Company reviewer dismisses a report whose code is not the Qt way of doing things ("you are not supposed to do
that") without looking at the bug. So the reproducer reads like a small, well-behaved application:

- **Qt's own facilities first.** A `QThreadPool` running `QRunnable`s, not Python's `threading`; a `QTimer` driving the
  GUI thread's work; signals and slots (`Signal`, `@Slot`) between `QObject` subclasses. Python's standard library
  only where Qt has no equivalent.
- **Nothing a Qt developer would call misuse.** Every object lives on the thread that made it; a `QImageReader` never
  outlives its device; no stop flag on a pool task -- bounded tasks and `waitForDone()` instead.
- **A familiar shape.** Name things after what an application does (a thumbnail loader, a job and the listener that
  follows it), not after the bug.
- **Ordinary Python.** Lifetimes follow from the code's shape (a temporary, a local), never from `del` tricks; no
  `__import__`, no reaching into private names.
- **Each choice that exposes the bug is marked.** The module docstring lists them, numbered and explained, and a
  `# Exposes the bug (n): ...` comment sits on the line that makes each one, so the reviewer sees at once which lines
  are the bug and that everything else is supported use. A loop that only turns a rare race into a frequent one says
  so.
- **The reviewer's first objection is answered first.** When the bug itself breaks a Qt rule (#652: a `QObject`
  destroyed off its thread), the docstring and the Description say up front who breaks it: PySide, not a line of
  the script.

## 3. Skimmable

[[[appendices.qt#skimmable]]]

- The module docstring says what the bug is, how the two sides meet, which choices expose it, how to run the script,
  what each exit code means, and **how long to wait**: a deadlock is silent until the watchdog fires.
- Every function and class has a docstring that says why it exists, not only what it does; comments only where the
  why is not obvious. Our code conventions hold ([[appendices.code-conventions#python]]): `Final` constants with
  docstrings, Sphinx docstrings, `@override`, no `_` names.
- **A deadlock runs in a child.** A deadlocked process cannot report or end itself (exit waits on the same locks), so
  `main()` only routes: `run_harness()` starts the same file again as the child and reports or kills it, and
  `run_child()` runs the loops under faulthandler's watchdog, which prints every thread's Python stack without
  needing the GIL. Each says so in its docstring.
- A `--with-format`-style flag runs the workaround, so the report shows the same script running clean. The
  workaround is the one the app uses, and it removes the cause rather than narrowing the window: #652's first one, a
  `deleteLater()` alone, still let the collector reach the object before the event loop did; a parent does not.

## 4. Proving it

[[[appendices.qt#proving]]]

- **Search Jira by the symptom once it is narrowed**, through the REST API
  (`/rest/api/2/search/jql?jql=project = PYSIDE AND text ~ "..."`). #659's "a base class's slot outlives its widget"
  narrowed to a base class's name-mangled method, and `text ~ "mangled"` found PYSIDE-3376, its other symptom
  (`sender()` is `None` there), already fixed in 6.12.0: no report, the issue closed with its measurements.
- **Measure the mechanism before writing the script.** Experiments in the scratchpad, then native stacks of a hung run
  (`py-spy dump --native --pid <child pid>`) showing each side holding what the other waits for. The issue's guess
  at the trigger can be wrong (#651's GUI side was a deletion, not a property assignment).
- **A stall is not a deadlock.** Busy Python threads can starve the GUI thread of the GIL for long enough to look hung
  (#652's first experiments). A real deadlock leaves the process near 0% CPU and its stacks unchanged between dumps.
  Measure and dump the real interpreter: a venv's `python.exe` is a launcher stub, always idle, whose child is the
  process to read.
- **Each cause the report names is checked by taking it away.** #652 says the connection between job and listener
  takes `~QObject` into Python: a copy of the script without the `connect` ran clean, and the report says so.
  #651's "each job must be new" was checked the same way after posting: one long-lived job ran clean on 6.11 and 6.12.
- **The version matrix**: PySide6 6.11 / Python 3.14, 6.12 / 3.14 and 6.12 / 3.15, by `uv run --python 3.x --with
  "PySide6-Essentials==6.1x.*" <name>.py`. `==6.11.*` resolves to the newest patch, not the app's locked one, and
  `--python 3.14` beside 6.12 once ran on 3.15 (#653): ask for the full version (`3.14.6`), and name the exact
  versions the script printed.
- Rerun after every change to the script, both the failing run and the workaround run, the workaround on every
  combination too.
- **Before handing over, read the pair against each other**: the script's docstring, the Description and the stacks
  tell one story (#652's docstring named one GIL path while its stack showed another).

### 4.1 Mechanisms found so far

[[[appendices.qt#mechanisms]]]

- **`~QObject` reaches Python under the signal-slot mutex.** While holding its own mutex it calls each sender's
  `metaObject()` and `disconnectNotify`; for a Python-built sender, PySide takes the GIL in either: in
  `retrieveMetaObject` (a Python subclass's meta-object), or in `Sbk_GetPyOverride` looking for a Python
  `disconnectNotify`, only on that object's first lookup, the "no override" answer then cached per object. Both were
  caught in native stacks (#651, #652). A reproducer needs a fresh sender each time; a plain `disconnect` unlocks
  before notifying, and never deadlocks (#654's mechanism too).
- **The thread under the mutex can be Qt's own.** Qt Multimedia's FFmpeg backend deletes, on its threads, objects it
  connected to a Python-built `QAudioOutput`, and that output's first `disconnectNotify` lookup takes the GIL there;
  the GUI thread meets it in `setAudioOutput`, which PySide calls with the GIL held (#654, PYSIDE-3514). To name the
  wrapper a native stack only shows as its module, answer its lookup early (connect and disconnect one of its
  signals on the GUI thread) and see the deadlock go. Several instances side by side (four players) turned a
  deadlock in half the runs into one in every run.
- **A worker's queued `emit` is never one side.** PySide releases the GIL around `QMetaObject::metacall` and takes
  it back only for the sender's `metaObject()`, under no Qt lock; `queued_activate` copies the arguments, a
  `PyObjectWrapper` taking the GIL, outside the receiver's mutex (PySide and Qt 6.11.1 and 6.12.0). A worker idle in
  `emit` is waiting for the GIL like any other thread: look for the thread that holds it. Emitting at a listener the
  GUI thread was destroying, its mutex held and the GIL wanted, ran clean on every version (#655).
- **A clean run counts only beside a control that deadlocks.** #655's first "clean" runs never put the GUI thread
  where the write-up said: `~QObject` calls a sender's `disconnectNotify` holding only the dying object's own mutex,
  and only for its incoming connections. The control (the same GUI loop against a PySide `disconnect` on an object
  sharing that pooled mutex, `shiboken6.getCppPointer(o)[0] % 131`) deadlocked at once, with the expected stacks.
- **A getter moves what it returns under its caller.** PySide is generated with the return value heuristic: a
  method returning a `QObject` makes the result's wrapper a Python child of the object it was called on, taken from
  the Python parent it had (exempt: names starting with `parent`, static methods, those with an ownership rule). When
  that caller is a Python-made object and is deleted, shiboken invalidates its Python subtree recursively: every
  wrapper of a Qt-made object in it reads "already deleted" while Qt still holds the object; Python-made ones are
  skipped. `subWindow.mdiArea()`, then that sub-window closed, killed the other documents' `addWidget` actions
  (#656, PYSIDE-3515); `nextInFocusChain()` and `QLabel.buddy()` move theirs too, `window()` does not.
  A wrapper freed with children does the same, with nothing deleted in C++: PySide wraps a Qt-made object it has no
  wrapper of for one call (a slot's argument, an event filter's `watched`), a getter called on it moves a Python
  tree under that wrapper, and the wrapper is freed as the call returns. #461's `container.dockWidget()` in a pin's
  slot killed a line edit's own actions that way (#365, #658); in PySide alone, `watched.childAt()` on a scroll
  area's viewport does (`qscrollarea_viewport_childat_invalidates_wrappers`, a comment on PYSIDE-3515). Asked for
  once by a getter (`scroll_area.viewport()`), such an object has a lasting wrapper and nothing is freed. Read the
  chain with `shiboken6.dump(obj)`'s `parent` line.
- **`shiboken6.dump` on 6.11.1 faults on a wrapper with an invalid neighbour.** It calls `str()` on the wrapper's
  Python parent, children and referred objects, never on its own C++ object; `str()` of an invalid one raises, and
  6.11.1 dereferences the NULL. An invalid wrapper stays in its Python parent's child list (Qt deleting an object it
  made only clears the wrapper's flag), so a live, valid line edit whose clear action Qt deleted faults. Fixed in
  6.11.2. #631's "valid while gone" wrappers were this, not freed objects (#657): probe with 6.11.2 or later.
- **One `uv run` of a script at a time.** Parallel runs of the same PEP 723 script race on its cached environment
  and fail to install.
- **The cyclic collector runs on whichever thread allocates.** Ordinary Python work on a pool thread can free a
  live, Python-owned `QObject` caught in a reference cycle there, and shiboken releases the GIL to run its C++
  destructor (#652).
- **PySide releases the GIL around its own `connect`**, but not around a Qt call that connects internally: a
  `QToolButton` re-applies its default action, with a fresh `connect`, at every change of that action (#529), or
  `QMediaPlayer`'s constructor, whose backend connects its own signals (#653). PySide's own `disconnect` keeps the
  GIL while it waits for the mutex (#653's experiments).

## 5. The Jira form

[[[appendices.qt#jira-form]]]

The `.md` follows the form's order, one heading per field: **Project** (Qt for Python, PYSIDE), **Issue Type** (Bug),
**Summary**, **Priority** (left at Not Evaluated), **Affects Version/s**, **Component/s** (PySide), **Environment**,
**Description**, **Attachment** (the `.py`).

- **The Description is plain Markdown**, written unfenced in the `.md`: the owner opens VS Code's Markdown preview
  and drags the rendered text into Jira's Description field, which takes no raw wiki text. Real `###` subheadings,
  bold labels (Expected, Actual, Workaround, Suggested fix), stacks in a code block.
- The one-line fields go in fenced blocks, copied as plain text. The file disables MD013 with a comment, since those
  blocks stay unwrapped.

## 6. After it is posted

[[[appendices.qt#after-posting]]]

- Read the posted issue through Jira's REST API (`https://qt-project.atlassian.net/rest/api/2/issue/<KEY>`; the
  browse page renders in JavaScript): every field, the description's formatting, and the attachment downloaded and
  compared byte for byte with the local `.py`.
- Our issue gets a comment linking the Qt issue, and **two labels: `upstream bug` and `pending cleanup`**. The
  script stays on the Qt issue only.
- **A reported issue stays open until Qt fixes it**, out of the release's milestone: it now tracks the Qt issue, so
  the workaround is removed when the fix ships (`gh issue list --label "upstream bug"` lists them). Its last comment
  gives each version's outcome, where the findings differ from the issue, and the workaround to remove, by file or
  rule. When the fix ships: rerun the reproducer on that version, remove the workaround, close.
- An issue that did not reproduce, or was not a bug of its own (#655), is closed as not planned with its
  measurements.
