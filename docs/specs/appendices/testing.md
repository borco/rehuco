# §A03. Testing and Cross-Platform QA

How rehuco's tests and static checks are structured and run, and the cross-platform gotchas that
took real time to work through — most of them surfaced by the **first full `make qa` run on
macOS** (issue [#15](https://github.com/borco/rehuco/issues/15)); several also gate the planned
cross-platform CI ([#14](https://github.com/borco/rehuco/issues/14)).

The guiding model (stated in the repo-root `conftest.py`): **each platform's test set runs on that
platform's own runner.** A test that can't apply on the current OS is *skipped*, not failed; code
that can't execute on the current OS is *excluded from coverage* there and measured on the runner
where it does execute.

## §A03.1 The QA gate

`make qa` runs, in order: `ruff format` + `ruff check --fix`, then `pytest` with coverage
(`make cov`), `bandit`, `pyright`, `pylint`. The test stack is `pytest` plus `pytest-mock`,
`pytest-qt`, `pytest-cov`, `pytest-benchmark`, `pytest-freezer`, and `pytest-explicit`. Tests live
beside their packages under `packages/*/tests` and `apps/*/tests` (`testpaths` in `pyproject.toml`);
`--strict-markers` is on, so every marker must be declared.

Each test's docstring ends with a `**Test steps:**` bullet list, so intent is readable without
tracing the code (a project convention, not a pytest feature).

## §A03.2 Qt tests must run headless

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

## §A03.3 Platform-conditional tests

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

## §A03.4 Static analysis across platforms

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

## §A03.5 Coverage of platform-specific code

Windows-only code can't run on a macOS/Linux qa pass, so it would count as missed: the whole
`platforms/windows/` package, and `__main__.py`'s two `if sys.platform == "win32":` branches.
Coverage config can't branch by platform, so two env vars gate it, each with a default that
*measures* everything (so nothing is silently dropped when unset, e.g. on Windows):

| Env var | pyproject key | Excludes |
| --- | --- | --- |
| `COV_OMIT_WIN` | `[tool.coverage.run] omit` (`${COV_OMIT_WIN-__no_such_path__}`) | the whole `platforms/windows/` package |
| `COV_EXCLUDE_WIN` | `[tool.coverage.report] exclude_also` (`${COV_EXCLUDE_WIN-(?!)}`) | the `__main__` win32 branches |

The subtlety: the vars must be set **in two places, for two runners** — because coverage is
initialized at different times depending on how pytest was launched:

- **`Makefile`** exports them (on non-Windows) for `make cov` and CI, where **pytest-cov reads the
  coverage config *before* the root conftest runs** — so a conftest-set value would be too late.
- **`conftest.py`** sets them for the **VSCode / IDE test runner**, which initializes coverage
  *after* the root conftest loads — so the Makefile env isn't present, but the conftest one is.

Setting both (via `export` / `os.environ.setdefault`) means whichever runner you use, the vars are
present before coverage reads its config. On Windows neither is set → defaults → the code is
measured, since the Windows test set exercises it. Net effect on macOS/Linux: `__main__.py` goes
42% → 100% and `platforms/windows/` drops out of the report.

A bare `coverage run` *without* pytest (no conftest, no make) would miss these — not a path this
project uses, but worth knowing if one is ever added.

## §A03.6 A build step that broke test *collection*

Not a test issue per se, but it first showed up as one: `pyside6-uic --python-paths` expects the
OS-native path separator (`;` on Windows, `:` elsewhere). The Makefile hardcoded `;`, so on
macOS/Linux uic couldn't resolve a `.ui`'s `.qrc` to its package and emitted a bare, unimportable
`import main_rc` — and **every `rehuco-agent` test then errored at collection** right after
`make uis` (`ModuleNotFoundError: No module named 'main_rc'`). Fixed by deriving the separator from
`$(OS)`. The lesson: a green `pytest` depends on `make uis` having generated correct, *importable*
`_ui.py`/`_rc.py` first (both are gitignored and rebuilt, never hand-edited).
