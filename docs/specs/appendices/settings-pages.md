# Settings Pages — Managing App-Wide Configuration

[[[appendices.settings-pages]]]

## Overview

[[[appendices.settings-pages#overview]]]

`SettingsDialog` (`rehuco_agent/settings/ui/settings_dialog.py`, #47) is a VLC-preferences-style
shell: a filterable category tree on the left, the selected category's page on the right, and a
toolbar with Save all / Save current page / Drop all / Drop current page. It holds no settings
content itself — every category is a `SettingsPage` (`settings/ui/settings_page.py`), a
`@runtime_checkable` `Protocol` an ordinary `.ui`-backed `QWidget` satisfies structurally, the same
style already used for the field toolkit's `StatefulWidget`/`FieldModel` ([[plugins#field-toolkit]]):

```python
class SettingsPage(Protocol):
    title: str
    def field_labels(self) -> list[str]: ...
    def is_dirty(self) -> bool: ...
    def save_changes(self) -> None: ...
    def drop_changes(self) -> None: ...
```

`MainWindow.__register_settings_pages` constructs each page and calls
`SettingsDialog.add_page(page)`; the dialog itself lives inside a floating-first, dockable
`DockableDialog` on the outer `CDockManager` (#47's dockable-dialog framework — out of scope here).

## 1. Save/Drop: what the toolbar actions do

[[[appendices.settings-pages#save-drop-actions]]]

The dialog shell dispatches, it never interprets:

- **Save all** / **Drop all** — call `save_changes()` / `drop_changes()` on every registered page,
  in registration order.
- **Save current page** / **Drop current page** — call it on whichever page's tree row is currently
  selected only.

What "saved" or "dropped" actually *means* is entirely up to each page. Two shapes exist today:

- **Staged-edit pages** (`MarkdownRenderingPage`) — edits live in local widget/draft state until
  `save_changes()` pushes them somewhere permanent; `drop_changes()` discards the draft and reloads
  the fields from whatever is currently saved (a revert, not a no-op).
- **Immediate-effect pages** (`RegistryPage`) — its buttons (Register/Unregister) already took
  effect on the OS the moment they were clicked; nothing is staged, so `save_changes()`/
  `drop_changes()` are no-ops and `is_dirty()` always returns `False`.

`is_dirty()` is reserved for a later dirty-badging slice on the category tree — declared on the
protocol, but not yet read by `SettingsDialog` itself.

## 2. How a page persists its own changes

[[[appendices.settings-pages#persisting-changes]]]

There is no generic persistence layer in the dialog shell — persisting is entirely each page's own
job, via whatever `save_changes()` does. `MarkdownRenderingPage`'s flow is the concrete pattern to
follow for a new staged-edit page:

1. `__sync_current_css_draft()` folds the visible CSS editor's text into whichever draft slot
   (`__markdown_css_draft`/`__mistletoe_css_draft`) matches the currently-selected engine radio —
   the two engines' CSS stay independent even though they share one editor widget.
2. The staged values (engine, both CSS drafts, image-width) are written onto the shared
   `MarkdownRenderingSettings` singleton (§4 below).
3. `settings.save(persistent_settings())` writes the now-current values to the on-disk `QSettings`
   ini.

`RegistryPage` has no local settings dataclass at all: Register/Unregister write straight to the
Windows registry via `rehuco_agent.windows_registration` when clicked, so there is nothing left for
`save_changes()` to do.

## 3. Adding a new settings page

[[[appendices.settings-pages#adding-a-page]]]

- One `.ui` + one `.py` per page, flat under `rehuco_agent/settings/ui/` (no further subdirectory —
  matches the one-file-per-unit convention already used for `fields/*.py`).
- Implement `SettingsPage` structurally: an ordinary `.ui`-backed `QWidget` subclass
  ([[appendices.code-conventions]]), no base class to inherit.
- Register it in `MainWindow.__register_settings_pages` via `self.__settings_dialog.add_page(...)`
  — the *first* page added becomes the initially-selected one.
- A platform-gated page (like `RegistryPage`, Windows-only) is imported lazily inside the
  `if sys.platform == "win32":` branch, and takes whatever app-level data it needs (e.g.
  `ARCHIVE_EXTENSIONS`) as a constructor parameter rather than importing it back from
  `main_window.py` — `main_window.py` already imports the page module (even if lazily) to construct
  it, so a module-level import the other way round is a cyclic import (confirmed empirically the
  first time `RegistryPage` tried it).
- `field_labels()` should return every user-facing label the page exposes, in no particular order —
  this is exactly what the tree's filter box (`SettingsDialog.CategoryFilterProxyModel`) matches
  against, alongside the page's own `title`: a plain case-insensitive substring match, not a regex.

## 4. Making the rest of the app react to a saved change

[[[appendices.settings-pages#reacting-to-changes]]]

A page's `save_changes()` only updates its own data (in memory and on disk) — it has no idea who
else in the app cares, and it never reaches into `DocumentsDock` or a specific viewer directly. The
live-update wiring instead lives on the settings *data* side:

- Unlike every other settings section in this app (`MainWindowSettings`, `DocumentSessionSettings`,
  … — plain `@dataclass`es with `load`/`save`), `MarkdownRenderingSettings` is a reactive `QObject`
  built from `borco_pyside.core.SimpleProperty` fields, each paired with a `<name>_changed` `Signal`
  (`engine_changed`, `markdown_css_changed`, `mistletoe_css_changed`, `max_image_width_changed`).
- `shared_markdown_rendering_settings()` (`functools.lru_cache(maxsize=1)`) is the single,
  process-wide instance every reader *and* writer uses. Constructing a fresh
  `MarkdownRenderingSettings()` per consumer would give each an independently-updating copy,
  defeating the whole point — there would be nothing left to "share."
- A consumer that needs to track live changes — `DescriptionField.__wire_rendering_settings`,
  wired from `make_viewer` — connects to every relevant `_changed` signal and re-applies the full
  current state in one call (`MarkdownView.apply_rendering_settings`) on any of them, so a Save
  touching several fields at once re-renders exactly once, not once per changed field.
- `save_changes()` assigning `settings.engine = ...` etc. on the shared singleton is what actually
  fires these signals (`SimpleProperty` only emits when a value genuinely changes). Persisting to
  disk (`settings.save(persistent_settings())`) is a separate step *after* that — the live update to
  already-open viewers doesn't depend on, or wait for, the `QSettings` write.

**Recipe for a new page that needs this same "already-open X reacts to Save" behavior:** give its
settings a reactive `QObject` (not a plain dataclass) with `SimpleProperty` fields and matching
`_changed` signals, expose it through one module-level `functools.lru_cache(maxsize=1)`-wrapped
accessor, and have consumers subscribe to the signals they care about instead of re-reading the
value on every use. Not every page needs this at all — `RegistryPage`'s actions land directly on the
OS, so there is no other part of the app that needs to be told a save happened.

**Testing note:** the `lru_cache`d singleton persists across test functions within one process, and
would otherwise leak state between tests (or read the developer's real on-disk settings) — see the
autouse `isolate_shared_markdown_rendering_settings` fixture in
`apps/rehuco-agent/tests/conftest.py`, which clears the cache and mocks `persistent_settings()`
around every test. A new page with its own shared reactive settings object needs the equivalent.
