# Spike: pyqtads + QML integration regression check

Throwaway spike for [#4](https://github.com/borco/rehuco/issues/4) (milestone `Pre-work`).
**Keep the lesson (this README + the wiring snippet).** The toy GUI is normally discarded,
but is **retained as a working reference until A0 reimplements the dock workaround** (the
`splitterSizes` stash/reapply is fiddly enough that porting from working code beats rebuilding
from notes) — delete `spikes/pyqtads-qml/` once A0 has consumed it.

## Decisions (2026-07-01)

- **Location:** top-level `spikes/pyqtads-qml/`, outside the uv workspace packages — keeps
  throwaway code clearly separated and easy to delete wholesale.
- **Environment:** a **throwaway venv local to this dir** (not added to any workspace
  `pyproject.toml`) — A0's tracer bullet hasn't committed to the `PySide6QtAds` dep yet, so
  the workspace stays clean.
- Branch: `issue/4/pyqtads-qml-spike`.

## What it tests

1. **Detach + re-dock** — the "QML view" dock (a `QQuickWidget`) drags out to a floating
   window and back without rendering glitches (classic QML cross-window trouble spot). The
   spinning square + the live `bridge.click_count` context property are the tells: if either
   breaks after a detach cycle, the wiring didn't survive.
2. **Coexistence** — a QML dock and QWidget docks (a table + the event log) live in one
   `CDockManager` layout.
3. **Layout save/restore** — *Layout → Save*/*Restore* round-trips `dock_manager.saveState()`.
   Close a dock (*View* menu toggles), restore, and check whether its **size** comes back.
   The app also stashes each dock's extent on close (keyed by object name) so we can compare
   the workaround against the raw blob.

## The reference wiring (the bit worth keeping)

Hosting QML in a QtAds dock is three lines (see `main.py`):

```python
quick = QQuickWidget(parent)
quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
quick.rootContext().setContextProperty("bridge", bridge)   # Python → QML
quick.setSource(QUrl.fromLocalFile(str(QML_FILE)))
# then: CDockWidget.setWidget(container_holding_quick)
```

Matches the proven pattern in `resource-hub` (`catalog_widget_view.py`) and `tutcatalog5`
(`logs/log_widget_ui.py`). Neither predecessor stress-tested detach or hidden-dock-size
restore — that is the new ground here.

## Run (after VSCode restart)

Set up the throwaway venv and launch. Note two gotchas:

- the PyPI package is **`pyside6-qtads`** (the import is `PySide6QtAds`);
- inside this uv workspace, `uv pip install` targets the workspace-root venv unless you
  point `--python` at the spike-local one.

```sh
cd spikes/pyqtads-qml
uv venv
uv pip install --python .venv/Scripts/python.exe "PySide6>=6.9" "pyside6-qtads>=4.5.0.3"
.venv/Scripts/python.exe main.py
```

Resolved versions here: PySide6 6.11.1, pyside6-qtads **5.0.0** (resource-hub used 4.5.0.4 —
this is the "current versions" the spike re-verifies).

## Findings

Run on PySide6 6.11.1 + pyside6-qtads 5.0.0 (2026-07-01).

- [x] Q1 detach/re-dock: **no glitches.** The QML dock detached to a floating window and
      re-docked cleanly — spinning animation kept running, no blank/black patches, and the
      `bridge` context object stayed live: clicking the QML button printed to the log dock
      **before, during, and after** the undock/re-dock cycle. Both wiring directions
      (Python→QML property, QML→Python slot) survived.
- [x] Q2 coexistence: **works.** QML dock + QWidgets table + log dock render together in one
      `CDockManager` layout.
- [x] Q3 layout save/restore + hidden-dock size: **save/restore of the layout blob works.**
      A closed dock does **not** recover its previous size from the blob alone (QtAds reopens
      it at a minimal size) — the anticipated soft spot. **The stash-on-close + apply-on-show
      workaround fixes it:** stash `dock_manager.splitterSizes(area)` on `closeRequested`,
      re-apply via `setSplitterSizes(area, sizes)` on `viewToggled(True)`, keyed by object
      name. Verified: reopened docks return to their previous size.

## Verdict

**The "both QML and QtWidgets in pyqtads docks" approach holds on current versions**
(PySide6 6.11.1, pyside6-qtads 5.0.0 — a major bump from resource-hub's 4.5.0.4). QML may
live in **detachable** docks; the detach-glitch fallback (non-detachable QML docks / reduced
QML footprint) is **not needed**. KDDockWidgets stays foreclosed by §16.7 regardless.

**Carry into A0:** the hidden-dock size restore is not automatic — A0's dock manager must
implement the `splitterSizes` stash-and-reapply workaround above, keyed by object name.
