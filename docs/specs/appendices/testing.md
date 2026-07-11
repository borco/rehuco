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
(`make cov`), `bandit`, `pyright`, `pylint`. The test stack is `pytest` plus `pytest-mock`,
`pytest-qt`, `pytest-cov`, `pytest-benchmark`, `pytest-freezer`, and `pytest-explicit`. Tests live
beside their packages under `packages/*/tests` and `apps/*/tests` (`testpaths` in `pyproject.toml`);
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

## 5. Coverage of platform-specific code

[[[appendices.testing#platform-coverage]]]

Windows-only code can't run on a macOS/Linux qa pass, so it would count as missed: the whole
`platforms/windows/` package, and `__main__.py`'s two `if sys.platform == "win32":` branches. It
must be dropped from coverage there, but still measured on the Windows runner — and coverage
config can't branch by platform.

The **wrong** way (tried first): gate it with env vars (`${COV_EXCLUDE_WIN-…}` in `exclude_also`,
`${COV_OMIT_WIN-…}` in `omit`) set from the Makefile and conftest. This fails, because *when*
coverage reads its config depends on how pytest was launched:

- `make cov` / CI (plain `pytest --cov`): pytest-cov reads the coverage config **before** the root
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
