# §A05. QtAds — Hurdles and Solutions

[[[appendices.qt-ads]]]

## Overview

[[[appendices.qt-ads#overview]]]

Engineering notes on `pyside6-qtads` behavior that took real time to work through, so a future
encounter with the same corner of QtAds doesn't have to re-derive it from scratch.

## §A05.1 `FocusHighlighting` and nested `CDockManager`s

[[[appendices.qt-ads#focus-highlighting]]]

**Symptom:** with `CDockManager.eConfigFlag.FocusHighlighting` on, focusing one dock also
highlights an unrelated dock in a *different* `CDockManager` — reproduced in rehuco-agent's
dock-in-dock-in-dock shell, which has three separate `CDockManager` instances sharing one native
top-level window (`MainWindow`'s own, `DocumentsDock`'s, and each per-document `DocumentWidget`'s
own — [[plugins#toolkit-surfaces]], [[plugins#viewer-editor-both]]): focusing a document tab in
the outer `DocumentsDock` also lit up that document's own inner viewer/editor split, and vice
versa. Confirmed via live logging on `focusedDockWidgetChanged`, not just visually. Not fixable at
the application level without abandoning the "documents tabbed together in one window" UX (making
each `DocumentWidget` a genuine separate top-level window, e.g. `Qt.Window` or an MDI subwindow,
would isolate it — a much bigger change than warranted for a cosmetic feature); the fix is to
avoid `FocusHighlighting` entirely — see §A05.1.3.

### §A05.1.1 Root cause: a shared `QWindow` property plus global signals

[[[appendices.qt-ads#cross-manager-contamination]]]

`CDockFocusController::updateDockWidgetFocus()` stores the newly-focused dock on the *shared
native `QWindow`*:

```cpp
if (Window)
{
    Window->setProperty(FocusedDockWidgetProperty, QVariant::fromValue(QPointer<CDockWidget>(DockWidget)));
}
```

Every `CDockFocusController` instance — one gets constructed per `CDockManager`, so three in this
app with one document open, one more per additionally-open document — connects to the same
*global* Qt signals in its constructor:

```cpp
connect(QApplication::instance(), SIGNAL(focusChanged(QWidget*, QWidget*)),
        this, SLOT(onApplicationFocusChanged(QWidget*, QWidget*)));
connect(QApplication::instance(), SIGNAL(focusWindowChanged(QWindow*)),
        this, SLOT(onFocusWindowChanged(QWindow*)));
```

So focusing *any* dock, in *any* manager, writes it into the shared window property, and *every*
other manager's own controller reads that same shared value and calls `updateDockWidgetFocus()`
on it too — using its own independent bookkeeping, regardless of whether that dock is even one of
its own. A `QMainWindow` subclass embedded as a child widget (e.g. `DocumentWidget`, itself a
`QMainWindow`, but placed via `dock.setWidget(...)` rather than shown as a genuine top-level
window) does not get its own `QWindow`: `QWidget.window()` always resolves to the nearest *true*
top-level ancestor, and in a dock-in-dock-in-dock shell there is exactly one such ancestor for the
whole app. Giving each nested manager a "separate" `CDockFocusController` would change nothing —
they'd all still share the one real window's property, since scoping follows the OS-level window,
not the `CDockManager`/`QMainWindow` instance asking.

### §A05.1.2 Compounding gotcha: silent no-op without the flag, deferred signal stacking

[[[appendices.qt-ads#requires-focushighlighting]]]

`setDockWidgetFocused()`/`focusedDockWidgetChanged` are silent no-ops without the flag at all (the
whole `CDockFocusController` only gets constructed when it's set, and only if set *before* the
first `CDockManager` in the process is built). Even with the flag on, `setDockWidgetFocused()`
does not synchronously emit `focusedDockWidgetChanged` for a dock that isn't visible yet (e.g.
during session restore, before `MainWindow.show()`) — `updateDockWidgetFocus()` defers the signal
until the dock's own `visibilityChanged(true)` fires. Calling it repeatedly on several invisible
docks in a row (once per reopened document, say) stacks up multiple deferred completions that all
fire in a burst, in whatever order Qt happens to deliver them, once the window is finally shown —
not necessarily the order they were queued in. Style updates themselves are *not* deferred (they
run synchronously, unconditionally, before the visibility check), so this specifically corrupts
signal-driven bookkeeping (e.g. "which dock is current"), not paint state — a red herring that
cost real time before §A05.1.1's shared-window-property cause was found.

### §A05.1.3 Fix: track focus via `CDockAreaWidget.currentChanged` instead

[[[appendices.qt-ads#current-changed-alternative]]]

Don't use `FocusHighlighting` at all when nested `CDockManager`s share a window. Track whichever
tab/dock matters using a signal that isn't gated by it instead: `CDockAreaWidget::currentChanged(int
index)` is a plain tab-bar signal — ordinary Qt tab-widget behavior, not routed through the
shared-window mechanism §A05.1.1 describes. Fires whenever the *current* (selected) tab within one
specific area changes, regardless of real Qt keyboard focus. Connect it once per distinct
`CDockAreaWidget` (`CDockManager.addDockWidget(...)` returns the area a dock ended up in —
multiple docks tabbed into the same area share one connection, so guard against connecting
twice), then resolve the tab index back to a dock via `area.dockWidget(index)`. This is what
`DocumentsDock` uses to track which document is "current" for the window title and
session-focus-save, with no cross-manager coupling at all.

### §A05.1.4 Confirm a binding exists before trusting a stub or the C++ header alone

[[[appendices.qt-ads#verify-bindings-live]]]

`pyside6-qtads` ships no official typings (see [[appendices.code-conventions]]'s notes on this
repo's own local stub, `typings/PySide6QtAds/__init__.pyi`) — a method visible in the upstream
C++ header is not guaranteed to be exposed to Python, and the local stub can also simply be
missing an entry that *is* bound. Before adding a new stub entry (or relying on one already
there), check the live binding directly:

```python
import PySide6QtAds as QtAds
print("currentChanged" in dir(QtAds.CDockAreaWidget))
print("dockWidget" in dir(QtAds.CDockAreaWidget))
```

This caught `CDockAreaWidget.dockWidget`/`.currentIndex`/`.currentChanged` all being genuinely
bound (confirmed against the upstream
[Qt-Advanced-Docking-System](https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System)'s
`DockAreaWidget.h` `Q_SIGNALS:`/public method declarations too) despite not yet being in the
stub — safe to add, once both checks agree. More generally: the upstream C++ source itself — not
just the Python bindings or this repo's own typings stub — is often the only way to actually find
a root cause once a QtAds behavior stops matching what the Python-side API surface alone suggests
it should do; clone the repo locally and read the relevant `.cpp`/`.h` directly (§A05.1.1 above
came from doing exactly that).
