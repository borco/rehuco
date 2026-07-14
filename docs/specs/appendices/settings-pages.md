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
    def is_dirty(self) -> bool: ...
    def save_changes(self) -> None: ...
    def drop_changes(self) -> None: ...
```

**Two-level filtering (#67).** The one filter box drives two nested filters off the same text, and a
page implements *neither* — both are the dialog's job, driven by a `SettingsFrameFilter`
(`settings/ui/settings_frame_filter.py`) the dialog builds for each page in `add_page`:

- **Page level** (`CategoryFilterProxyModel`) — the category tree shows every page whose `title` or
  any frame's gathered text contains the filter text.
- **Frame level** — a page groups its controls into labeled `QFrame`s; the currently-shown page hides
  every frame not matching the text, so a crowded page collapses to just the group being searched
  for. **The frame is the smallest unit shown or hidden** — never a single control inside one.

`SettingsFrameFilter` **discovers** a page's top-level `QFrame`s and **gathers** each one's searchable
text by introspection — walking its child widgets for user-visible captions (`QLabel` text, button
text, `QGroupBox` titles) once, at construction. So a page needs no hand-maintained term list: the
filter tracks whatever the `.ui` actually says, including renamed labels and translations, and never
recomputes per keystroke. (Only exact-type `QFrame`s count as groups, so a `QFrame` subclass like a
decorative rule isn't mistaken for one.)

A **"Show full page if title matches"** `WrappingCheckBox` (`borco_pyside.widgets`) sits under the
filter box. When checked, text matching a page's title shows that page in full — every frame —
regardless of which individual frames also match; when unchecked, the title is ignored for frame
visibility and only the frames whose text matches are shown (so a title-only match shows no frames).
Either way, a page still appears in the tree on a title *or* frame match. The dialog re-runs the
current page's frame filter whenever the filter text or the toggle changes, and whenever a different
page becomes current.

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
- Group the page's controls into labeled top-level `QFrame`s in the `.ui` (a bold header `QLabel`
  plus the controls). That is *all* a page does for filtering — the dialog discovers the frames and
  gathers their searchable text by introspection (§Overview), so a page implements no `field_labels`
  or `apply_filter` and keeps no term list. The frame is the smallest filterable unit — don't split a
  group's controls across separate frames expecting them to hide independently.
- Give the page's root layout zero margins (the stack already provides padding) and end it with a
  vertical spacer so frames stack at the top rather than stretching to fill. If one frame holds a
  control that should grow (e.g. `MarkdownRenderingPage`'s CSS editor), stretch that frame's layout
  item so it — not the spacer — takes the slack when shown, while the spacer keeps a lone remaining
  frame top-aligned. Set that stretch in the controller after `setupUi()` (`main_layout.setStretch`),
  not in the `.ui`: the current `pyside6-uic` mistranslates a box-layout `stretch` property.

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
