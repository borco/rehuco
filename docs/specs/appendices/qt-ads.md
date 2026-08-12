# QtAds — Hurdles and Solutions

[[[appendices.qt-ads]]]

## Overview

[[[appendices.qt-ads#overview]]]

Engineering notes on `pyside6-qtads` behavior that took real time to work through, so a future
encounter with the same corner of QtAds doesn't have to re-derive it from scratch.

## 1. `FocusHighlighting` and nested `CDockManager`s

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
avoid `FocusHighlighting` entirely — see [[appendices.qt-ads#current-changed-alternative]].

### 1.1 Root cause: a shared `QWindow` property plus global signals

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

### 1.2 Compounding gotcha: silent no-op without the flag, deferred signal stacking

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
cost real time before [[appendices.qt-ads#cross-manager-contamination]]'s shared-window-property
cause was found.

### 1.3 Fix: track focus via `CDockAreaWidget.currentChanged` instead

[[[appendices.qt-ads#current-changed-alternative]]]

Don't use `FocusHighlighting` at all when nested `CDockManager`s share a window. Track whichever
tab/dock matters using a signal that isn't gated by it instead: `CDockAreaWidget::currentChanged(int
index)` is a plain tab-bar signal — ordinary Qt tab-widget behavior, not routed through the
shared-window mechanism [[appendices.qt-ads#cross-manager-contamination]] describes. Fires whenever
the *current* (selected) tab within one
specific area changes, regardless of real Qt keyboard focus. Connect it once per distinct
`CDockAreaWidget` (`CDockManager.addDockWidget(...)` returns the area a dock ended up in —
multiple docks tabbed into the same area share one connection, so guard against connecting
twice), then resolve the tab index back to a dock via `area.dockWidget(index)`. This is what
`DocumentsDock` uses to track which document is "current" for the window title and
session-focus-save, with no cross-manager coupling at all.

### 1.4 Confirm a binding exists before trusting a stub or the C++ header alone

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
it should do; clone the repo locally and read the relevant `.cpp`/`.h` directly
([[appendices.qt-ads#cross-manager-contamination]] came from doing exactly that).

## 2. The full signal set a "current dock" tracker needs

[[[appendices.qt-ads#current-dock-signals]]]

`CDockAreaWidget.currentChanged` ([[appendices.qt-ads#current-changed-alternative]]) is necessary
but **not sufficient** — it only fires
when a *tab index within one area* changes, and several ways of making a dock "current" don't do
that. `QtAdsFocusTracker` (`borco_pyside.qtads`) is the reusable home for the whole set, each part
added only after confirming empirically that the others miss its case:

- **`CDockAreaWidget.currentChanged`** — ordinary tab-bar switching within a shared (tabbed) area.
- **the area's tabs-menu `QMenu.triggered`** — picking an area's *already-current* lone tab from
  its dropdown never changes `currentChanged`'s index, so it fires nothing.
- **the dock's own tab-label `clicked`** (`tab_label(dock)` → the `CElidingLabel` named
  `dockWidgetTabLabel`) — a dock alone in its area is always index 0, so clicking its tab never
  changes `currentChanged` either.
- **`QApplication.focusChanged`** — real keyboard focus moving into a *different, already-visible
  split area* changes no area's current-tab index at all. Walk up `parentWidget()` from the newly
  focused widget to find the enclosing tracked `CDockWidget`.
- **`CDockWidget.viewToggled`** — a dock hidden/shown by its `toggleViewAction` fires *none* of the
  above. Show → make it current. Hiding the *current* dock: Qt moves keyboard focus to a neighbor
  **synchronously, before `viewToggled` fires** (verified: `focusWidget()` already points at the
  sibling inside the `viewToggled(False)` slot), so `focusChanged` has already re-selected that
  real neighbor and the toggle handler is reached only when nothing tracked took focus — clear
  then, rather than fabricate a current dock no focus points at. Guard the whole handler with
  `CDockManager.isRestoringState()`: `restoreState` fires `viewToggled` for every reconstructed
  dock, which would fight the explicit re-selection in [[appendices.qt-ads#restore-current-split]].

Deliberately **not** the tab *title*: current-ness is shown by a dynamic `tracked_focus` QSS
property + highlight styling on the tab (a `FocusHighlighting`-free equivalent of QtAds' own
`focused` property), so callers own their titles outright and there is no marker-vs-dirty-suffix
conflict from two writers touching one `windowTitle`.

## 3. `restoreState` doesn't restore which *split* area was current

[[[appendices.qt-ads#restore-current-split]]]

`CDockManager.saveState`/`restoreState` records only the current *tab within each area*, never
which of several *split* areas held focus. So docks tabbed together restore their current tab
fine, but a viewer/editor split into two areas always comes back current on whichever dock was
adopted first (the viewer), losing the real selection. Persist it yourself: save the current
dock's `objectName()` alongside the manager state, and after `restoreState` (which re-registers
every dock by name) re-select it with `CDockManager.findDockWidget(name)` +
`set_current_dock` — this is `QtAdsFocusTracker.save_state`/`restore_state`. Note `restoreState`
rebuilds every affected `CDockAreaWidget` from scratch, orphaning `currentChanged` connections
made before it — re-track areas on `stateRestored` — and fires `viewToggled`/`currentChanged` for
the reconstructed docks *during* the call, hence the `isRestoringState()` guard in
[[appendices.qt-ads#current-dock-signals]].

## 4. Recoloring a tab close button: the icon is stylesheet-governed, not code-set

[[[appendices.qt-ads#tab-close-button]]]

**Symptom:** the `[x]` close-button icon goes invisible against a themed/highlighted tab, and
`color:` in QSS can't tint it. Root cause (found by reading QtAds' `DockWidgetTab.cpp` and its
bundled `default.css`): the close button's icon comes from the default stylesheet's
`#tabCloseButton { qproperty-icon: url(:/ads/images/close-button.svg); qproperty-iconSize: 16px; }`
rule, which **wins over both** the C++ `internal::setButtonIcon` *and*
`CDockManager.iconProvider().registerCustomIcon(TabCloseIcon, …)` at polish time — so neither
code path can change the icon in the installed build, and a `url()` SVG icon ignores QSS `color:`
regardless — and all four of 5.0's sheets carry that rule, so the workaround holds whichever is live
(but see [[appendices.qt-ads#stylesheet-reload]]: QtAds *replaces* the sheet when the palette flips,
so the override has to be re-applied, not merely applied once).
What *does* follow the palette is **text**: render the close mark as the button's
**text** (a glyph — ideally from a bundled icon font, e.g. Phosphor, loaded via
`QFontDatabase.addApplicationFont`, since a system-font glyph's metrics vary per platform), color
it with `color: palette(...)`, and hide the real icon with `qproperty-iconSize: 0px`. Two timing
traps: (1) do the icon-size zeroing in **QSS**, because QtAds re-polishes the button on every tab
activation and would re-apply the 16px size otherwise; (2) set the glyph's font/size and a square
`setFixedSize` in **Python on a deferred (`QTimer.singleShot(0)`) tick**, because QtAds re-sets the
button *after* emitting `dockWidgetAdded` (and after a restore) for the tab it then makes active,
overwriting an eager restyle. `TabCloseButtonIsToolButton` aside, the button is a `QPushButton`
named `tabCloseButton`, reachable via `dock.tabWidget().findChild(QAbstractButton, "tabCloseButton")`.

### 4.1 Why the override is allowed to win: specificity first, source order only as the tiebreak

[[[appendices.qt-ads#qss-cascade]]]

The zeroing rule beats QtAds' `16px` for one reason and one reason only: **it is appended after it**.
Both are plain `#tabCloseButton` id selectors, so they tie on specificity, and Qt implements CSS2.1
cascading — a tie is broken by source order, last one wins. Verified directly rather than taken from
the docs, since the whole workaround rests on it:

| Stylesheet | Wins |
| --- | --- |
| `#target { red }` then `#target { green }` | green — **last** |
| `#target { green }` then `#target { red }` | red — last, symmetric |
| `#target { green }` then `QLabel { red }` | green — **the id, despite being first** |
| `QLabel { red }` then `#target { green }` | green — the id again |
| `#tabCloseButton { 16px }` then `#tabCloseButton { 0px }` | `iconSize == 0` |

The middle two matter as much as the rest: order never *overrides* specificity, it only settles ties.
So the append order in `QtAdsFocusTracker` is load-bearing, not cosmetic — read QtAds' sheet,
concatenate ours **after** it. Prepending would silently hand the last word back to `16px` and
restore the doubled close mark, which is also why the re-append following every
`setColorSchemeMode` reload has to put the block at the end again
([[appendices.qt-ads#stylesheet-reload]]).

The `tracked_focus` highlight is not in this position: `ads--CDockWidgetTab[tracked_focus="true"]`
adds an attribute selector on top of the type selector, outranking QtAds' plain
`ads--CDockWidgetTab` rules on specificity, so it would win in either order. Only the close-button
override depends on being last.

## 5. A fully custom tab widget crashes when routed through `CDockComponentsFactory`

[[[appendices.qt-ads#custom-tab-widget]]]

**Question (spike #60):** can QtAds's tab widget be replaced wholesale with a custom widget, rather
than styling/appending to the bundled one (as in [[appendices.qt-ads#tab-close-button]])? **Finding:**
partially — the sanctioned extension point exists and is bound, but returning a Python-subclassed tab
through it crashes; a different, code-only path covers the actual need instead.

### 5.1 The extension point is bound, and works for the title bar/tab bar

[[[appendices.qt-ads#components-factory-bound]]]

QtAds's own extension point for this is `CDockComponentsFactory` (`DockComponentsFactory.h`): a global
factory whose `create...` virtuals (`createDockWidgetTab`, `createDockAreaTitleBar`,
`createDockAreaTabBar`, `createDockWidgetSideTab`) build every dock/tab/title-bar widget instance,
replaceable wholesale via `CDockComponentsFactory.setFactory(...)`. `pyside6-qtads`'s `bindings.xml`
does bind it (`object-type`, all four virtuals), with inject-code on `setFactory` specifically to keep
a Python override callable afterwards — confirmed live too (`setFactory`/`createDockWidgetTab` both
present in `dir(QtAds.CDockComponentsFactory)`, per [[appendices.qt-ads#verify-bindings-live]]'s rule of
never trusting the header alone). Overriding `createDockAreaTitleBar`/`createDockAreaTabBar` alone, each
returning a plain (non-subclassed) base-class instance from Python, works end-to-end through
`addDockWidget` with no crash.

### 5.2 But a Python-subclassed `CDockWidgetTab` segfaults on insertion

[[[appendices.qt-ads#custom-tab-segfault]]]

**Symptom:** overriding `createDockWidgetTab` to return a *Python subclass* of `CDockWidgetTab` — even
an empty one whose `__init__` does nothing but call `super().__init__()` — builds the tab object fine
(the override runs and returns successfully during `CDockWidget()` construction itself, before any dock
area exists), then **segfaults** later inside `addDockWidget`/`addDockWidgetTabToArea`, the moment
QtAds' C++ side tries to insert that tab into its area's tab bar. Isolated to a 5-line repro; not
present when `createDockWidgetTab` is left at its default, or overridden to return a vanilla
(non-subclassed) `CDockWidgetTab`. Root cause not chased past this point (out of scope for a spike):
`bindings.xml` marks `CDockAreaTabBar::insertTab(int, ads::CDockWidgetTab*)`'s tab argument `parent
action="add"` — ordinary Qt-parent reparenting for a C++-constructed pointer, but likely mishandled by
shiboken's shell/ownership machinery when the pointer instead originates from a Python virtual-function
return. Not an application-level mistake to work around: a fully custom Python-defined tab class routed
through the sanctioned factory hook is not viable in the current binding.

### 5.3 Working alternative: extend the default tab's own layout post-construction

[[[appendices.qt-ads#tab-layout-insert]]]

Skip the factory/subclass path entirely. After `addDockWidget()`/`addDockWidgetTabToArea()`,
`dock.tabWidget()` still returns the ordinary C++-built `CDockWidgetTab`; inserting an extra widget
straight into its own `layout()` works with no crash and needs no `CDockComponentsFactory` registration
at all. The default layout is, left to right: `dockWidgetTabLabel` (title, stretch 1) → spacing →
`tabCloseButton` → trailing spacing (`DockWidgetTabPrivate::createLayout()`) — confirmed by walking
`layout().itemAt(i)` after construction. `layout().insertWidget(1, widget)` lands a new widget between
the title and the close button; `insertWidget(0, widget)` lands it ahead of the title. Being a real
child `QWidget` rather than a stylesheet-driven icon (contrast [[appendices.qt-ads#tab-close-button]]),
it takes an ordinary `clicked` signal connection with none of that section's icon-recoloring workarounds.

## 6. Customizing or disabling the per-area tabs menu

[[[appendices.qt-ads#tabs-menu]]]

**Question (spike #60 follow-up):** the "tabs menu" — the dropdown behind `TitleBarButtonTabsMenu`,
shown once an area's tabs overflow/elide — lists every tab in that area, built straight from each tab's
`text()`/`icon()`/`toolTip()`. Since `DocumentsDock.__update_dock_title` bakes the dirty/locked marker
into `CDockWidget.windowTitle()`
([documents_dock.py:29](../../../packages/rehuco-agent/src/rehuco_agent/documents/documents_dock.py#L29)),
that marker shows up in this menu too, with no separate state to key a color off. Three questions:
can the menu's contents be changed (e.g. two-line entries instead of a tooltip)? Can the whole menu be
replaced with a custom widget? Can it be disabled for one `CDockManager` only (the outer documents
dock) while staying on for others (the per-document editor/viewer splits, #61's actual replacement)?

### 6.1 Contents are rebuildable — no subclassing needed

[[[appendices.qt-ads#tabs-menu-rebuild]]]

`CDockAreaTitleBar::onTabsMenuAboutToShow()` is a **private**, non-virtual slot — there's no override
hook for it (contrast `buildContextMenu`, which is `virtual` and `public`). But the button and its menu
are both reachable through public API: `titleBar.button(QtAds.TitleBarButtonTabsMenu).menu()`. QtAds
connects its own rebuild to that menu's `aboutToShow` in the title bar's constructor, which runs before
application code can reach the button at all — so any later `menu.aboutToShow.connect(...)` from Python
fires *after* QtAds' own rebuild on every open, letting a handler `menu.clear()` and repopulate freely
without racing it. Confirmed: replacing each plain `QAction` with a `QWidgetAction` wrapping a small
`QWidget` (bold name label over a full-path label) renders correctly — real two-line entries, no
tooltip-on-hover needed. Click-to-switch still works for free: QtAds' own `onTabsMenuActionTriggered`
just reads `action->data().toInt()` as the tab index, so a replacement action only needs `setData(i)` to
keep that behavior.

### 6.2 The button/menu itself has no factory hook — it's hardcoded

[[[appendices.qt-ads#tabs-menu-no-factory]]]

Unlike the tab widget ([[appendices.qt-ads#components-factory-bound]]), `TabsMenuButton` is built
directly in `DockAreaTitleBarPrivate::createLayout()`, not routed through `CDockComponentsFactory` at
all. There is nothing to subclass or replace wholesale here, safely or otherwise — augmenting the
existing menu's contents (§6.1) is the only lever, matching the same "extend after construction" shape
as [[appendices.qt-ads#tab-layout-insert]].

### 6.3 Disabling it for one manager only needs reactive re-hiding, not just a flag

[[[appendices.qt-ads#tabs-menu-per-manager]]]

`DockAreaHasTabsMenuButton` (`eConfigFlag`) is a `CDockManager` **static** — shared process-wide across
every manager, same category as [[appendices.qt-ads#requires-focushighlighting]]. Turning it off is
all-or-nothing; it cannot single out one manager (e.g. the outer documents dock, per #61) while leaving
others (per-document editor/viewer splits) on.

A genuinely per-manager alternative exists: `CDockManager.dockAreaCreated(area)` fires only for areas
created under that specific manager instance — confirmed an outer manager's connection never fired for
an untouched inner manager's area. But naively hiding the button synchronously from that signal doesn't
stick: `DockContainerWidgetPrivate::onVisibleDockAreaCountChanged()` unconditionally forces the tabs-menu
button back to visible whenever a container's visible-area-count transitions to/from exactly 1 (the
sole/"top-level" area case), on **both** add and remove, regardless of any flag -- confirmed empirically
(a hide made during `dockAreaCreated` reverted itself for the first/sole area, and later removing a
second/split area reverted the first area's hide too). Fix: defer the hide with
`QTimer.singleShot(0, ...)` — the same "let QtAds' own synchronous bookkeeping finish first" shape as
[[appendices.qt-ads#tab-close-button]]'s icon-restyle timing trap — and re-apply it from **both**
`dockAreaCreated` (new areas) and `dockWidgetRemoved` (re-hide every remaining area, since removal can
also flip the count through 1). With both hooked and deferred, an outer manager's button stayed hidden
through add, split, and remove, while an untouched inner manager kept the global default.

## 7. `pyside6-qtads`'s vendored `libxkbcommon` crashes Qt on Linux mouse motion

[[[appendices.qt-ads#libxkbcommon-race]]]

**Symptom:** on Linux (confirmed under WSLg's Wayland platform plugin), the app builds and shows
fine, then segfaults the instant the mouse enters any window — a `gdb` backtrace shows the crash
inside `atom_intern()`/`xkb_state_mod_name_is_active()`, called from Qt's own (official)
`QXkbCommon::modifiers()` during `QWaylandInputDevice::Pointer::pointer_motion`.

**Root cause:** the `pyside6-qtads` wheel vendors its own private copy of `libxkbcommon` under
`pyside6_qtads.libs/`. `PySide6QtAds.so` is a normal Python C extension, loaded with global symbol
visibility, so importing it adds its private `libxkbcommon` to the process's *global* symbol scope.
Linux's dynamic linker resolves an unversioned symbol name (`atom_intern`, etc.) by searching that
global scope in load order and using the first match — for *every* caller, regardless of which
literal file that caller's own dependency list names. If `import PySide6QtAds` runs before Qt's own
`libxkbcommon.so.0` (the system copy `libQt6Gui.so.6` itself directly depends on) has been loaded,
QtAds' copy wins that race and Qt's real keyboard/pointer-modifier handling gets silently rebound to
it — an ABI-incompatible build it was never tested against.

**Fix:** import anything from `PySide6` proper before `import PySide6QtAds` anywhere in the process
(confirmed with `gdb`: constructing a `QApplication` first is enough, the crash disappears).
`rehuco_agent/app.py` is the app's actual entry point for this — its own `import PySide6QtAds as
QtAds` is placed *after* its `PySide6.Qt*` imports, marked `# isort: skip` so `ruff`'s import
sorter (which otherwise sorts plain `import` statements before `from ... import` ones, undoing the
order) leaves it alone. No other file needs the same treatment: Python caches modules, so only the
*first* `import PySide6QtAds` anywhere in the process matters, and `app.py` is always that first
one on the real startup path.

Filed upstream: [mborgerson/pyside6_qtads#123](https://github.com/mborgerson/pyside6_qtads/issues/123).

**Resolved upstream in `5.0.0.2`** (released 2026-08-04): the manylinux wheel no longer vendors
`libxkbcommon` at all (`ci: Don't vendor libxkbcommon in manylinux wheels`), so the race this section
describes cannot happen on a wheel built from that fix onward — confirmed via the diff between the
`v5.0.0` and `v5.0.0.2` tags on `mborgerson/pyside6_qtads`. This also drops a duplicate copy of
`libxkbcommon` (and whatever it pulls in) from what the Linux AppImage build has to bundle, on top of
closing the crash. `pyside6-qtads`'s floor is `>=5.0.0.2` for exactly this, alongside the submodule
fix below. `app.py`'s import order is left as-is regardless — there's no harm in it, and it costs
nothing to keep protecting a build resolved below the floor.

## 8. Every `CDockManager` carries QtAds' default stylesheet — nesting pays for it per level

[[[appendices.qt-ads#per-manager-stylesheet]]]

**Symptom:** switching between open document tabs is visibly slow, on every switch and not just the
first — 77.8 ms in rehuco-agent's dock-in-dock-in-dock shell with three documents open, measured
offscreen (#234).

**Root cause:** `CDockManager`'s constructor applies QtAds' bundled `default.css` (9 359 characters)
to *itself*, so an app that nests managers — one outer, one per open document — holds one copy per
level, and Qt re-evaluates all of them against the whole subtree on every repolish, which a tab
activation triggers. What costs is each additional stylesheet-carrying **ancestor**, near enough
regardless of what that sheet contains (see the table below).

**Fix:** let exactly one widget in the nest carry the QSS. QSS cascades, so an ancestor's sheet
already styles every nested manager's chrome, and a nested manager's own copy buys nothing —
`setStyleSheet("")` on it is visually free (verified: full-window grabs before and after are
**pixel-identical in both light and dark themes**) and halves the switch: 77.8 ms → 40.7 ms.
`QtAdsFocusTracker`'s `stylesheet_host` parameter is the seam — given a host, the tracker appends its
tracked-focus rules there (once, however many trackers share it) and clears its own manager's sheet.

Measured alternatives, each a fresh process over the same three documents:

| Where the styling lives | Sheet | Switch |
| --- | --- | --- |
| One copy per manager, five managers | 9 852 × 5 | 77.8 ms |
| The outermost manager only — **the fix** | 9 852 | 40.7 ms |
| Outermost manager, QtAds' `default.css` only (no focus rules) | 9 359 | 36.2 ms |
| Outermost manager, the focus rules only (no `default.css`) | 492 | 36.2 ms |
| The whole sheet hoisted to `QApplication` instead | 9 852 | 52.7 ms |
| No stylesheet anywhere (chrome unstyled — not shippable) | 0 | 11.4 ms |

Three things worth keeping from that table. **The cost is a step, not a slope**: 492 characters and
9 359 characters on one manager both measure 36.2 ms against 11.4 ms for nothing at all, so ~25 ms is
the price of that subtree having *any* stylesheet-carrying ancestor, and only the last ~4 ms scales
with what is in it. That is why hoisting is worth 37 ms and trimming the surviving sheet is worth
almost nothing. **`QApplication` is not the same fix**: an application sheet is evaluated against
every widget in the process, where a manager's reaches only its own subtree. And **what the surviving
sheet buys** is the current-tab highlight, the close-button glyph
([[appendices.qt-ads#tab-close-button]]) and the dock borders — dropping it entirely is the 11.4 ms
row, and would mean marking the current tab without QSS at all.

A floated dock keeps its chrome: a stylesheet reaches a child widget even when that child is a
top-level window (verified with a `Qt.Tool` `QLabel` parented to a styled widget — it renders
styled), and QtAds parents its floating containers to the manager they came from.

## 9. QtAds **replaces** its own stylesheet at runtime — pin the colour scheme to own the timing

[[[appendices.qt-ads#stylesheet-reload]]]

**Symptom:** after a light↔dark switch, no tab reads as current any more and every tab shows QtAds'
`[x]` icon **and** the glyph drawn as the button's text — two close marks per tab
(#227, surfaced by #234).

**Root cause:** ADS 5.0 added dark-mode support with `CDockManager::ColorSchemeMode::FollowPalette`
as the **default**, and re-runs its own `loadStylesheet()` from `CDockManager::eventFilter` on an
`ApplicationPaletteChange` — calling `setStyleSheet(...)`, which **replaces**. Everything appended to
that sheet is gone, including [[appendices.qt-ads#current-changed-alternative]]'s `tracked_focus`
highlight and §4's `qproperty-iconSize: 0px`. Measured in a real window (light → dark):

| | manager stylesheet | appended rules |
| --- | --- | --- |
| before the flip | 9 852 | present |
| after the flip | **9 478** | **gone** |

Four sheets ship, not one — `default.css` (9 359), `default_dark.css` (9 478), and the two
`default_linux*` variants — which is why the length changes rather than merely the content.

**Re-appending afterwards cannot be timed against it.** Qt fires `ApplicationPaletteChange` several
times per switch and QtAds reloads off a *later* one than a coalescing notifier
(`ApplicationPaletteChangeNotifier`) emits for, so a re-append from that signal is simply overwritten
again — confirmed: the rules were still gone afterwards. Reacting to the carrier's own `StyleChange`
does work, but an event filter on a dock manager was rejected as too costly.

**Fix: pin the mode.** `setColorSchemeMode(Light|Dark)` stops the event-driven reload entirely, and
reloads once, synchronously, at the call — so the re-append that follows it is deterministic.
`QtAdsFocusTracker` pins on construction and re-pins on every palette change, choosing by
`CDockManager.isApplicationPaletteDark()` (QtAds' own test), then re-applies its rules. Verified in a
real window: after the flip the manager carries the **dark** sheet plus the appended rules (9 971),
the current tab is still highlighted, and every close button still reports a zeroed icon size.

Two traps worth keeping. `setColorSchemeMode` reloads exactly when the call **changes the effective
dark-ness** (verified: re-pinning the same scheme leaves an appended marker untouched; pinning the
other one wipes it) — but since the caller can't cheaply know whether a given call flips it, the
re-append follows every call unconditionally (it no-ops when the rules survived), and it must land
**at the end** of the reloaded sheet ([[appendices.qt-ads#qss-cascade]]).
And the reload hands a **nested** manager back a full default sheet, undoing the one-sheet-per-nest
arrangement of [[appendices.qt-ads#per-manager-stylesheet]]; re-clearing it belongs in the same step.

`eConfigFlag.DisableStylesheet` would be the blunter lever — QtAds applies no sheet at all and the
app owns styling outright. It exists in upstream ADS 5.0 but was **not bound in `pyside6-qtads`
5.0.0** (`dir(CDockManager.eConfigFlag)` did not list it, the
[[appendices.qt-ads#verify-bindings-live]] check applied to a flag an issue body had recorded as
available) -- and *is* bound as of `5.0.0.2` (confirmed the same way against the installed wheel).
Not adopted: pinning the mode already solves the problem this section is about, and switching levers
now would trade a working, tested fix for an untested one on the strength of a binding gap that has
since closed.
