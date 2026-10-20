# Testing and Cross-Platform QA

[[[appendices.testing]]]

## Overview

[[[appendices.testing#overview]]]

Test-writing conventions (docstring format, etc.) live in [[appendices.code-conventions#testing]]; this page
is about how rehuco's tests and static checks are structured and run, and the cross-platform gotchas that
took real time to work through — most of them surfaced by the **first full `make qa` run on
macOS** (issue #15); several also gate the planned
cross-platform CI (#14).

The guiding model (stated in the repo-root `conftest.py`): **each platform's test set runs on that
platform's own runner.** A test that can't apply on the current OS is *skipped*, not failed; code
that can't execute on the current OS is *excluded from coverage* there and measured on the runner
where it does execute.

## 1. The QA gate

[[[appendices.testing#qa-gate]]]

`make qa` runs, in order: `ruff format` + `ruff check --fix`, then `pytest` with coverage
(`make cov-parallel`, which CI runs too, #545), `bandit`, `pyright`, `pylint`. The test stack is `pytest` plus
`pytest-mock`, `pytest-qt`, `pytest-cov`, `pytest-benchmark`, `pytest-freezer`, and `pytest-explicit`. Tests live
beside their packages under `packages/*/tests` (`testpaths` in `pyproject.toml`);
`--strict-markers` is on, so every marker must be declared.

## 2. Qt tests must run headless

[[[appendices.testing#headless-qt]]]

**Symptom:** running the Qt-touching tests (`ApplicationSingleton`, the agent app/viewer tests)
without an active window server — a CI runner, or macOS over SSH — **segfaults** (exit 139) during
`QLocalServer`/`QLocalSocket` teardown *across* tests. Each test passes in isolation; the crash is
an ordering/teardown interaction. The C stack shows `libqcocoa` / `NSApplication run`: Qt is
driving a real native event loop.

**Fix:** force Qt's headless platform. The repo-root `conftest.py` does, before any test module
builds a `QApplication`:

```python
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
```

`setdefault` so a developer on a real desktop session can still `QT_QPA_PLATFORM=cocoa pytest ...`
to watch windows during GUI debugging. None of conftest's own imports pull in Qt, so setting it at
conftest import time is early enough.

**Linux needs more than `offscreen`** (surfaced by the cross-platform CI in #14; the fix above was only ever
exercised on macOS, where it sufficed). On the `ubuntu-latest` leg the same `test_application_singleton.py`
still segfaulted (exit 139) with `offscreen` set — this time the C stack ran through
`QEventDispatcherGlib::processEvents` → `QCoreApplicationPrivate::sendPostedEvents` into a
`~QLocalServer` → `deleteChildren` → `~QLocalSocket` chain, i.e. a deferred `deleteLater()` firing
during teardown. Root cause: `ApplicationSingleton.shutdown()` disposes of its `QLocalServer` (and
the sockets it accepted) via `deleteLater()`, but `qtbot.wait()` runs a *nested* event loop, and
`DeferredDelete` events posted at a different loop level are not reliably reaped there. On Linux's
glib dispatcher they instead accumulate across tests and eventually crash when a server is destroyed
after one of its child sockets was already freed. (macOS's cocoa dispatcher happened to reap them in
an order that didn't crash, which is why `offscreen` alone looked sufficient there.)

**Fix:** the `make_singleton` fixture's teardown flushes the deferred deletions explicitly, so each
test disposes of its own Qt objects instead of leaving them for a later test's event loop:

```python
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
qtbot.wait(10)
```

Every `ApplicationSingleton` this fixture builds is `shutdown()`- then-flushed, so no queued
`deleteLater()` crosses a test boundary. This is a test-harness concern only: a real app runs
`app.exec()` to completion, whose event loop (and the `QApplication` destructor on exit) reap
`DeferredDelete` continuously, so nothing accumulates.

## 3. Platform-conditional tests

[[[appendices.testing#platform-tests]]]

Two distinct mechanisms, for two distinct needs:

- **Per-test platform markers.** `pyproject.toml` declares `windows` / `macos` / `linux` markers;
  the repo-root `conftest.py`'s `pytest_collection_modifyitems` skips any test whose marker doesn't
  match the running `sys.platform`. Use this for a test that only makes sense on one OS but lives
  in a normally-importable module.

- **Whole-file skip via `importorskip`.** A test file that imports a module absent on other
  platforms guards it at the top so the *entire file* is skipped where the import would fail:

  ```python
  winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows
  ```

  (Subsequent imports then need `# noqa: E402` / `pylint: disable=wrong-import-position`, since they
  legitimately follow the guard.)

**Simulating another platform in a cross-platform test.** A test that asserts the *non-Windows*
code path can force it anywhere with `monkeypatch.setattr("sys.platform", "linux")`. But mocking a
Windows-only API from such a test is a trap: `ctypes.windll` doesn't exist off Windows, and

```python
mocker.patch("ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID", create=True)  # WRONG
```

raises `AttributeError` — `create=True` only creates the *leaf* attribute, but `mock` still
traverses `ctypes.windll` first. Patch the whole attribute instead (its parent `ctypes` exists, so
`create=True` can add it) and assert on the nested mock:

```python
windll = mocker.patch("ctypes.windll", create=True)
...
windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_not_called()
```

This works identically on all platforms (on Windows `windll` already exists; `create=True` is then
a harmless no-op).

## 4. Static analysis across platforms

[[[appendices.testing#static-analysis]]]

`win_registration.py` uses Windows-only stdlib (`winreg`, `ctypes.windll`), which the linters flag
when qa runs on macOS/Linux:

- **pyright** raised 14 `reportAttributeAccessIssue` errors, because those symbols are
  `sys.platform == "win32"`-gated in typeshed. Fixed with `pythonPlatform = "All"` in
  `[tool.pyright]`, which makes platform-gated stdlib resolvable regardless of host — the right
  setting for a project with per-platform modules.

- **pylint** raised `E0401` (`import-error`) on `winreg`. Fixed with `ignored-modules = ["winreg"]`
  in `[tool.pylint.typecheck]`. A per-line `disable=import-error` can't be used: `useless-suppression`
  is enabled, so it would itself be flagged on Windows, where the import resolves fine. A
  module-level ignore is platform-safe.

### 4.1 pylint and pyright traps

[[[appendices.testing#lint-traps]]]

- **A pragma goes stale when the code under it changes** (#470, #404): delete it. `make pylint` hides
  `useless-suppression`; check with `uv run pylint --enable=useless-suppression <paths>`. Messages can also flicker
  between identical runs (#343); a pragma for one of those names `useless-suppression` too.
- **`pylint_qt` reads any `obj.attr[i]` as a subscripted signal** in a module importing PySide (#376, #457, #485):
  bind to a local or unpack (`(mime,) = call.args`, never `call.args[0].urls()`).
- **Pyright's PySide stubs lack some members**: `QKeySequence.__getitem__`, `QObject.staticMetaObject`,
  `CDockAreaWidget.currentDockWidget` (use `dockWidget(currentIndex())`). The QtAds stub is hand-kept: add a member the
  code or a test newly uses (#491: `createAndSetupAutoHideContainer`, `AutoHideFeatureEnabled`).
- **A module-level annotation's name can be undefined and the import still succeed** (#459): only ruff and pyright
  catch it.
- **Import what a test patches from where it is defined** (#464). pylint cannot infer a mock's recorded argument
  (`not-callable`): call it in a helper with one reasoned pragma.
- **pylint refuses `bar` as a name** (#392, #376), and **a name-mangled call through another instance reads as
  unused** (#400).

## 5. Coverage of platform-specific code

[[[appendices.testing#platform-coverage]]]

Windows-only code can't run on a macOS/Linux qa pass, so it would count as missed: the whole
`platforms/windows/` package, and `__main__.py`'s two `if sys.platform == "win32":` branches. It
must be dropped from coverage there, but still measured on the Windows runner — and coverage
config can't branch by platform.

The **wrong** way (tried first): gate it with env vars (`${COV_EXCLUDE_WIN-…}` in `exclude_also`,
`${COV_OMIT_WIN-…}` in `omit`) set from the Makefile and conftest. This fails, because *when*
coverage reads its config depends on how pytest was launched:

- `make cov` / `make cov-parallel` / CI (plain `pytest --cov`): pytest-cov reads the coverage config **before** the root
  conftest runs — so a conftest-set var is too late; only a Makefile-exported one works.
- The VSCode test runner invokes `pytest --cov=. --cov-branch` directly (no `make`), and reads
  config at yet another moment — so neither the Makefile env nor a timely conftest value is
  reliably present.

No single env-setting site covers all three runners.

The **right** way: a **coverage configurer plugin** (`coverage_platform.py`, registered via
`[tool.coverage.run] plugins`). Coverage calls it at its own initialization regardless of how
pytest was launched, so one mechanism covers `make cov`, a bare `pytest --cov`, and VSCode alike.
On non-Windows it appends `*/platforms/windows/*` to `run:omit` and the `if sys.platform ==
"win32":` regex to `report:exclude_lines`; on Windows it does nothing, so that code is measured by
the Windows test set. Net effect on macOS/Linux: `__main__.py` goes 42% → 100% and
`platforms/windows/` drops out of the report.

Two implementation notes worth keeping:

- **Append to `report:exclude_lines`, not `report:exclude_also`.** By the time the configurer
  runs, coverage has already folded `exclude_also` into `exclude_lines` (the list actually matched
  against source); appending to `exclude_also` then has no effect.
- **The plugin module must be importable when coverage starts** — very early, in pytest-cov's
  `pytest_load_initial_conftests`. `[tool.pytest.ini_options] pythonpath = ["."]` puts the repo
  root on `sys.path` in time; without it the plugin fails with `ModuleNotFoundError`.

## 6. A build step that broke test *collection*

[[[appendices.testing#qualified-rc-imports]]]

Not a test issue per se, but it first showed up as one: `pyside6-uic --python-paths` expects the
OS-native path separator (`;` on Windows, `:` elsewhere). The Makefile hardcoded `;`, so on
macOS/Linux uic couldn't resolve a `.ui`'s `.qrc` to its package and emitted a bare, unimportable
`import main_rc` — and **every `rehuco-agent` test then errored at collection** right after
`make uis` (`ModuleNotFoundError: No module named 'main_rc'`). Fixed by deriving the separator from
`$(OS)`. The lesson: a green `pytest` depends on `make uis` having generated correct, *importable*
`_ui.py`/`_rc.py` first (both are gitignored and rebuilt, never hand-edited).

## 7. Reading a QA run

[[[appendices.testing#reading-a-run]]]

- **A green summary line is not a green check** (#402). `make qa` stops at the first red step, pylint prints
  `10.00/10` even when failing, and an `echo` after a background `make` reports the wrong code. Run
  `make qa > log; echo $?` from the repo root, then grep the log for `: [CRWE]NNNN:`, `^FAILED`, `error:` and
  `Error N`. `make pyright`'s summary goes to stderr: read `*>&1` in PowerShell.
- **Run `make` from Git Bash on Windows** (#343): PowerShell breaks `uname`, so `make uis` silently does nothing.
- **A hung `make` or pytest keeps running after it is stopped** (#459). Find its `uv`/`pytest`/`python` children by
  command line (`Get-CimInstance Win32_Process`) and stop only those; never `taskkill /IM python.exe` (#102), and never
  `git stash` across such a run. A clean second worktree, detached at master, runs master's suite beside a branch.
- **A parallel `cov` failure is rarely the newest diff.** Re-run on master, reproduce deterministically, and fix a race
  with a gate job occupying the worker ([[appendices.testing#races]]), never a longer wait.

## 8. Probing the real app

[[[appendices.testing#probing]]]

- **Probe a stated premise before building on it** (#393, #345, #373, #407, #454, #457, #485): ten lines on a scratch
  tree. Every one of these turned out false: "a sub-dock can float", "`None` vs `0` separates unmeasured from empty",
  "`QLabel.pixmap()` drops the device-pixel ratio" (it follows the label's). Query the real cache read-only before
  trusting a total.
- **Headless, a bare `MainWindow()` writes the real config on teardown** (#400, #461, #491). Before any app import,
  call `set_settings_dir(scratch)` (#494; it moves the `.ini`, `config_folder()` and `cache_folder()` into `scratch`). Copy the user's
  config files in, run `Application(argv).show_main_window()`, and end with `os._exit(0)` so nothing saves back. A
  real `RootsPanel` (#457) needs `RootCatalog(queue, resource_events=events)`, `RehuDocument.new` records and a poll on
  `queue.jobs()`. A bare-QtAds probe needs the auto-hide flags ([[appendices.qt-ads#auto-hide-flags]]).
- **Launch a development build with `--settings-dir`** (#494), from the `rehuco-agent (local settings)` configuration
  (`.local_settings`). Without it a second launch forwards to whichever agent is already running and exits
  ([[nodes#single-instance]], #460), so the window on screen can be another checkout's: "primary already running …
  forwarded argv" in the run log says so, and each run's `argv` there says which build it was.
- **A flash is invisible to the suite** (#306): probe with a watchdog thread that writes its findings and calls
  `os._exit`.

## 9. Races and background work

[[[appendices.testing#races]]]

- **A state a fast background job passes through is held with a gate** (#484): patch the job's reader to
  `release.wait()`, assert the intermediate state, then set the event (also at teardown). Without the gate the test
  passes by timing alone.
- **A stale-answer guard runs on the GUI thread, not the worker** (#470): emit `(serial, result)` and judge it in a
  slot; prove it with `QThreadPool.waitForDone()` between the answer and the switch.
- **`TaskQueue.wait_until_idle` is true before a just-enqueued job starts** (#457): poll the job's state.
- **A server that never answers is a real listener with a full queue** (#482): `listen(0)`, then
  `create_connection(timeout=0.05)` until one raises `TimeoutError` (assert that, not just `OSError`); proven on Windows
  and Linux.
- **A fake clock replaces the module's own `time` name** (`mocker.patch("pkg.mod.time",
  SimpleNamespace(monotonic=clock))`), never `time.monotonic`, which Qt and pytest-qt read.
- **An unclosed SQLite connection warns under whichever test the GC runs in** (#372). A shared-cache memory database
  takes table locks WAL never does: "table is locked" in parallel runs only (`PRAGMA read_uncommitted`, #377).
- **A worker crash with no assertion is often a `QThread` destroyed while running** (3324cf1): reproduce it with a
  worker that lingers after `super().run()`.
- **A native crash in pytest-qt's `_process_events` is an earlier test's deferred work** (#102): run the file 8–12
  times, narrow it with targeted `sendPostedEvents(obj, DeferredDelete)`, and fix the source.
- **Stale connections are countable** (#380): `obj.receivers("2" + signature)` around a build and teardown, plus
  `sendPostedEvents(None, DeferredDelete)`.
- **Gating a lightbox decode** (#479): gate `ArchiveImageSource.load` only when `max_height is not None` (the main
  image loads on the GUI thread); clear `QPixmapCache` per test; monkeypatch `roots_lightbox.ThumbnailLoader`.

## 10. Driving Qt offscreen

[[[appendices.testing#offscreen-qt]]]

- **Synthetic input goes to the widget under the point** (#485): `viewer.childAt(p) or viewer`, mapped with `mapFrom`,
  then moves to the widget that took the press. Sending straight to a container skips its children's hit-testing, so a
  test of "the band takes the press" passes vacuously.
- **`qtbot.mouseMove` can be dropped under load** (#321, #378, #462, #457): `QApplication.sendEvent` a `QMouseEvent`.
  Text can draw no ink once an icon font has loaded: assert on `drawText` calls through a `QPainter` subclass (keep the
  `QImage`). `QIcon.paint` never reaches a Python `drawPixmap`: read pixels. Skip ink-dependent tests where text draws
  nothing (#465).
- **Text does not scale linearly** (#462): enlarge until the part overflows, and assert that.
- **Key presses** (#344, #345): a `MainWindow` test window never activates, so assert on `shortcuts()`; a bare host
  `QMainWindow` that is shown, activated and waited on takes a real `ApplicationShortcut` press.
- **A PySide signal is cached on the instance after first access** (#462): patch the instance, not the class. Make
  `emit` raise `RuntimeError` rather than `shiboken6.delete` a widget. An unshown widget gets no `resizeEvent`.
- **`startDragDistance()` is 0 without an application** (#395): take `qtbot`.
- **A disabled `QAction.trigger()` does nothing, and the settings dialog refreshes enablement on a timer** (#457): call
  `__refresh_dirty_ui` between staging and triggering.
- **An empty-area menu is testable offscreen** (#469): show, resize, `waitExposed`, pick a point below a column's
  `viewport()`, and patch the module's `QMenu` with a recording `exec`.
- **A modal question lives behind a public method of its owner** (#344), which the fixture replaces per instance.
- **A Scintilla autocomplete popup on a shown editor corrupts the heap offscreen** (#343): `autoCCancel()` first, and
  use `QWidget.setFocus(editor)`.
- **A test's shown window must be held** (#491): a window built in a helper and dropped dies with its wrapper, taking
  its dock managers along ("already deleted" at the first call); a generator fixture yields while holding it. A
  `.show()` without `qtbot.addWidget` leaks a window (#383).
- **A mock widget handed to a `MainWindow` is saved and closed at teardown** (#464): set `dirty = False` and
  `save_state.return_value = b""`, or the real modal pops or `QByteArray` fails.
- **A test that loads a model in place keeps every tab and the form alive** (#470): build all tabs, and hang the form
  on the returned surface (`all_editors`).
- **The clipboard is the shared `clipboard` fixture** in `conftest.py`, which restores what the developer had in a
  `finally` (#485). A `QDrag` is replaced and the staged name asserted through a real `ImageExporter`, never a
  `Mock(spec=…)`.
- **Drags in tests** (#387, #461, #485): send `DragEnter` before `Drop` and keep the `QMimeData` alive; only events to
  `window.windowHandle()` exercise parent routing. A synthetic `DragMove` after an ignored enter never reaches any event
  filter (dropped in `QApplication.notify`, the application's included): hand it to the installed filter's
  `eventFilter` directly.

## 11. The suite's own fixtures and patches

[[[appendices.testing#suite-fixtures]]]

- **A real folder is pytest's `tmp_path`, nothing hand-rolled** (#475); never mock `Path.mkdir`. A `/fake/…` path is
  a real `C:\fake` on Windows, and a `C:/x` literal is absolute only there — a key needs an absolute path, so root a
  fake one at `Path(Path.cwd().anchor)` (#414's tests passed on Windows and failed on macOS and Linux).
- **What is tested elsewhere is mocked here** (#545): a class's own tests prove it; every other test assumes it works,
  and a break gets a test of that class. The Root Catalog docks tests run `RootCatalog` over a `Mock(spec=Catalog)`
  (`catalog`) and patch `CatalogCache.open` with a `MagicMock` (`cache`) for the jobs and notifiers; `cached_rows` is
  what both answer from, as far as their contracts say (`hold`), and no agent test opens SQLite. The window tests
  build `MainWindow` over stub settings pages and every document they open over stub sub-docks, the Documents dock's
  tests their documents over the same stub (`stub_settings_pages`, `stub_sub_docks`, module-wide); a test of the real
  ones asks for `real_settings_pages` or `real_sub_docks`. Only a class's own tests, and core's contract tests
  (`test_catalog_snapshot`), run the real cache.
- **The agent suite's `Path.stat` answers a missing file with a `Mock`** (#458): `touch()` first, or use
  `real_path_stat` (#395). The session's settings, data and cache folders are temporary (`isolate_app_folders`, #412).
- **The `served` fixture patches `Path.read_text` for every file** (#469): re-patch it to serve `.rehuco` only
  (`REAL_READ_TEXT`). A checksum record is `{"version": 1, "files": [{name, xxh3, verified, status}]}`.
- **The suite swaps `persistent_settings` in its own module for an in-memory fake** (#494): a test of the real override
  patches the real function back; `reset_settings_dir` (autouse) clears the override. Native window titles can be read
  with `GetWindowTextW`; a top-level title lacking the application display name gets it appended.
- **`mocker.patch.object(instance, "method")` misses a collaborator built with the bound method** (#456): hand it the
  object.
- **Fixtures are imported by name from a sibling module** (`test_catalog_docks`' `fixture_catalog`/`served`/`saves`,
  a card list's page; #487, #493) and keep their name (`@fixture(name=…)`, as `fixture_dock`). Past the size cap a
  test module splits the same way ([[appendices.code-conventions#python]]).
- **Test helpers' id counters start far above explicit ids** (#379). **Never build expected text from the checkout's
  path** (#398): a never-shown menu elides it.
- **A platform branch is a module constant** so a test can flip it (#402).
- **A "defaults when nothing was saved" test seeds the instance first** (#483): loading into a fresh object whose
  defaults are already empty passes whatever `load()` does. Prove such a test by making `load()` a bare `return`.
- **Test each half of a split toggle against the other** (#408).
- **Assert a query plan one clause at a time** (#454): `set_trace_callback` + `EXPLAIN QUERY PLAN`, no `SCAN r`. An
  `OR` uses an index only when every term is on the table's indexed columns; prove the test by restoring the old
  clause.
- **A coverage gap in an untouched file is real** (#462, #344, #457): reach a defensive branch with a test, or delete a
  guard no caller can reach. An `elif` loop that can skip is a partial branch: filter in a comprehension.
- **A bad zip by patching bytes** (#480, #484): `writestr(ZipInfo)` resets `flag_bits`, so set it in the central
  directory entry afterwards (`PK\x01\x02` + 8 is the flag byte; encrypted is bit 0); swap a UTF-8 name's bytes for
  invalid ones of the same length; blank the `PK\x01\x02` signature to leave the end record intact over a corrupt
  directory. Both packages keep a copy of `crafted_zips.py`.
- **`make check-slugs` reads `[[x.y]]` in test code** (#485): `== [[widget.action]]`, a list of lists, trips it.

## 12. Finding what only the cyclic collector frees

[[[appendices.testing#cycle-diagnostic]]]

- [#529: make qa hangs on Windows: GIL / Qt signal-slot mutex deadlocks](https://github.com/borco/rehuco/issues/529)

A Python-owned `QObject` whose wrapper sits in a reference cycle is destroyed whenever the cyclic collector next runs,
on whichever thread allocated — a pool thread included, where `~QObject` takes a signal-slot mutex and then waits for
the GIL the GUI thread may hold (#529). `qtbot` does not prevent it: its teardown closes and `deleteLater()`s only the
widgets registered with `addWidget`.

To list what each test leaves for the collector, run the suites with this throwaway plugin. It switches automatic
collection off for the whole run, so nothing is collected on a pool thread, and after each test's teardown runs one
collection on the main thread with `DEBUG_SAVEALL`: everything found is kept alive (no PySide finalizer runs, so the
segfault a blanket `gc.collect()` once caused cannot happen) and recorded against that test, one JSON line per test
with garbage, a file per xdist worker.

```python
"""Throwaway pytest plugin: which tests leave Qt wrappers that only the cyclic collector would free (#529)."""

import gc
import json
import os
from collections import Counter
from pathlib import Path

import pytest
from shiboken6 import Shiboken

OUT = Path(os.environ["GC_CYCLES_OUT"])
KEEP: list[object] = []


def _write(entry: dict) -> None:
    with (OUT / f"cycles-{os.getpid()}.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry) + "\n")


def _type_name(obj: object) -> str:
    kind = type(obj)
    return f"{kind.__module__}.{kind.__qualname__}"


def _live_and_python_owned(obj: object) -> bool:
    try:
        return Shiboken.isValid(obj) and Shiboken.ownedByPython(obj)
    except TypeError:  # a mock with a Qt spec passes the isinstance check
        return False


def _collect(nodeid: str) -> None:
    gc.disable()
    gc.collect()
    garbage = list(gc.garbage)
    gc.garbage.clear()
    KEEP.extend(garbage)  # never destroyed: no finalizer runs
    wrappers = [obj for obj in garbage if isinstance(obj, Shiboken.Object)]
    if wrappers:
        others = Counter(_type_name(obj) for obj in garbage if not isinstance(obj, Shiboken.Object))
        _write(
            {
                "test": nodeid,
                "wrappers": dict(Counter(_type_name(obj) for obj in wrappers)),
                # only these run a C++ destructor when collected
                "live_owned": dict(Counter(_type_name(obj) for obj in wrappers if _live_and_python_owned(obj))),
                "others": dict(others.most_common(8)),
            }
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    OUT.mkdir(parents=True, exist_ok=True)
    gc.disable()
    gc.set_debug(gc.DEBUG_SAVEALL)
    _collect("<session start>")


def pytest_runtest_setup(item: pytest.Item) -> None:
    del item
    gc.disable()  # a test may have switched it back on


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None):
    del nextitem
    yield
    _collect(item.nodeid)
```

Save it as `gc_cycles.py` in a scratch folder (never in the repo), then from the repo root, in Git Bash:

```bash
GC_CYCLES_OUT=<scratch>/out PYTHONPATH=<scratch> uv run pytest packages/rehuco-agent/tests \
    packages/borco-pyside/tests -n auto -p gc_cycles -p no:cacheprovider -q --timeout=600
```

About 16 minutes on the development machine; memory grows, since nothing found is ever freed. Reading the output:

- **`live_owned` is what matters**: a wrapper whose C++ object is still alive and owned by Python. The rest are empty
  shells or children their parent owns, harmless to collect.
- **Of those, only `QObject` subclasses take a signal-slot mutex** when destroyed. Value types (`QPersistentModelIndex`,
  `QPixmap`, `QColor`, `QKeySequence`, `QRect`) cannot deadlock this way.
- **Fix at the source, plainly**: a `QObject` the app builds gets a parent (usually `self`); a fixture gives what it
  builds a parent the test tears down, or deletes it explicitly (`deleteLater()`, then
  `QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)`, as `make_action` does). A test hands
  what it builds bare to the `delete_at_teardown` fixture (the repository conftest). Re-run until no `QObject` with
  connections is left under `live_owned`.
- **Left on purpose** (#529): a `QObject` with no signal connections — a mocked `QDrag`'s recorded `QMimeData`, a
  `QBuffer`, a `QCheckBox` — whose `~QObject` never takes a signal-slot mutex; and pytest-qt's own `QEventLoop`, built
  inside `waitSignal`, which is a third party's.
