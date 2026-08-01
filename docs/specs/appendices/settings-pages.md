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
  any frame's gathered text contains the filter text (and, per the group rules in
  [[appendices.settings-pages#category-groups]], every page of a matching group).
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

**Only the pages scroll (#229).** `add_page` wraps each page in a widget-resizable `QScrollArea` of its
own and stacks *that*, so a tall page scrolls while a short one sits still. **One per page, not one
around the stack**: a `QStackedWidget` reports its tallest page's height as its own, so a shared scroll
area would scroll a two-row page by the longest page's length. Everything around the stack — the
toolbar, the filter box, both toggles and the category tree — is chrome that stays put however small the
dialog gets, since a control the user cannot reach is a setting they cannot change. The tree is not
wrapped either: a `QTreeView` already is a scroll area, and nesting them gives two sets of scrollbars
and a tree that can be scrolled out of its own viewport.

`MainWindow.__register_settings_pages` constructs each page and calls
`SettingsDialog.add_page(page)`; the dialog itself lives inside a floating-first, dockable
`DockableDialog` on the outer `CDockManager` (#47's dockable-dialog framework — out of scope here).

## 1. Category groups (#76)

[[[appendices.settings-pages#category-groups]]]

The category tree is **two levels deep at most**: `add_page(page, group="Plugins")` nests the page's
row under that group's row, creating the group's row on first use; `add_page(page)` leaves it a
top-level row of its own. Today **Plugins** holds "Descriptions" (`DescriptionsPage`), "Excluded
Files" (`ExcludedFilesPage`, #226) and "Images" (`ImagesPage`) — registered in that alphabetical
order — and "System Integration" (`RegistryPage`) is top-level. Group names are plural — a group holds
pages, and **Plugins** is where a resource type's own settings go.

**One page per subject, not per owner.** "Images" gathers every image-shaped setting whichever object
owns it: the viewer surface and thumbnail strips (`ImageViewerSettings`), the width cap on an image
embedded in a description (`MarkdownRenderingSettings`), and which archive entries a reference-images
resource counts as its images (`ReferenceImagesSettings`, #222). The last two arrived from elsewhere —
the cap was a block on Descriptions, the extension list a "Reference Images" page holding nothing but
that list. Both were filed where the *code* owned them, so finding either meant knowing which plugin
or settings object to look under, when what the reader had was the word "images". A page whose one
block is a list is also a tree row that costs a click to learn it holds one thing.

A group row **carries no page of its own** — it is a header. Selecting it shows every page under it
at once, stacked vertically in one scrolling column, each preceded by its title as a heading — since
the tree selection no longer names which page is which once several are shown together (#230). A
group holding one page shows just that one. Selecting a leaf page directly, whether or not a group
was shown before it, re-parents that page out of any group column and back into its own single-page
view — a page has one parent, so this is a move, never a second copy. The live frame filter composes
with this: a shown group filters every one of its pages' frames, not just one, which is a better
answer to "where is that setting" than paging through children one by one. Everything that walks
pages (Save all / Drop all, and now Save/Drop *current page* on a selected group row) recurses one
level into groups, so a grouped page is never skipped.

A **second `WrappingCheckBox`, "Show full group if title matches"**, sits under the page-level one and
makes the tree filter group-aware:

- **checked** — text matching a *group's own title* shows every page under it, even pages whose own
  title/fields don't match;
- **unchecked** — filtering stays page-scoped: a group's title has no say in its pages' visibility (so
  a group-title-only match shows nothing at all).

A page matching the filter on its own merits is shown either way, whatever its group. A group row is
shown exactly when at least one page under it is: Qt hides a rejected parent's whole subtree, so
`CategoryFilterProxyModel.filterAcceptsRow` **accepts a group row on its children's behalf** (a group
can never be shown empty, and a page can never be hidden by its group alone). A filtered-out group row
takes its leaves' expansion state with it, so the dialog re-expands the tree after every re-filter —
otherwise a page could survive the filter yet stay unseen.

**The whole filter state persists** across restarts — the filter text and both toggles — via
`SettingsDialogSettings` (`settings/settings_dialog_settings.py`). The dialog restores it in
`__init__`, *before* wiring the widgets' signals up, so seeding them doesn't immediately re-save what
was just loaded; the proxy is seeded by hand for the same reason (no signal to ride in on). Each
page's own frame filter needs no seeding: a page is frame-filtered when it becomes current, and the
first page added becomes current immediately.

Saving is `SettingsDialog.save_filter_state()`, called from `MainWindow.closeEvent` alongside the
app's other at-shutdown saves (window state, session, recent files, theme) — the dialog lives in a
dock, so it has no close/done path of its own to save from the way `UnsavedChangesDialog` (a real
`QDialog`) does from `done()`. Saving per keystroke instead would mean one ini write per character
typed into the filter box, for no gain.

**Testing note:** because construction alone touches persistent storage, the autouse
`isolate_settings_dialog_settings` fixture in `packages/rehuco-agent/tests/conftest.py` patches the
dialog's `persistent_settings()` — otherwise any test building one (directly, or via `MainWindow`)
would read and overwrite the developer's real settings file, and leak toggle state into later tests.

## 2. Save/Drop: what the toolbar actions do

[[[appendices.settings-pages#save-drop-actions]]]

The dialog shell dispatches, it never interprets:

- **Save all** / **Drop all** — call `save_changes()` / `drop_changes()` on every registered page,
  in tree order (a group's pages together, at the group's own position).
- **Save current page** / **Drop current page** — call it on the selected leaf page, or on every page
  under a selected group row (#230) — the same one-level recursion Save all / Drop all already do,
  now also driven by what the tree's current row is rather than always every page.

What "saved" or "dropped" actually *means* is entirely up to each page. Two shapes exist today:

- **Staged-edit pages** (`DescriptionsPage`, "Descriptions"; `ImagesPage`, "Images";
  `ExcludedFilesPage`, "Excluded Files") — edits live in
  local widget/draft state until `save_changes()` pushes them somewhere permanent; `drop_changes()`
  discards the draft and reloads the fields from whatever is currently saved (a revert, not a no-op).
  `ImagesPage` is the one page writing **three** settings objects, one per block, each saved whole
  because that is the unit its own `save()` takes. Writing `MarkdownRenderingSettings` there
  re-persists the engine and CSS unchanged: what the shared object holds is already the last-saved
  pair, so a `DescriptionsPage` edit still staged is neither picked up nor clobbered.
  `ImagesPage` writes a **reactive** singleton (`ImageViewerSettings`, §5's recipe), because applying
  it has to show its own effect on what is already on screen: every open document's image strip
  resizes and takes up the chosen layout — one row or wrapped ([[plugins#tutorial-plugin]]) — and
  every open maximized viewer resizes and shows or hides its own thumbnail row. Only
  `mode` stays read-at-open-time — it decides where the *next* viewer is built, and nothing already up
  can follow a change to it.
  One of its values is deliberately only a **starting point**: `strip_visible` decides whether a
  maximized screenshot opens with its thumbnail row *the first time* a document shows one
  ([[plugins#tutorial-plugin]]). Toggling that row inside a viewer never writes back here — it is that
  document's own view state, and lives in its saved layout beside which tabs it has open — because a
  shared setting would let one document's toggle decide how every other document's viewer opens.
  Applying it does reach the viewers *currently open*, so the effect is visible where the user is
  looking, and each of those documents then remembers the applied value as if its toggle had been
  clicked by hand. A document with no viewer open resolves the setting afresh whenever it opens one,
  so it is never seeded with a stale default from whenever it happened to be constructed.
- **Immediate-effect pages** (`RegistryPage`, "System Integration") — its buttons
  (Register/Unregister) already took effect on the OS the moment they were clicked; nothing is
  staged, so `save_changes()`/`drop_changes()` are no-ops and `is_dirty()` always returns `False`.

`is_dirty()` is reserved for a later dirty-badging slice on the category tree — declared on the
protocol, but not yet read by `SettingsDialog` itself.

## 3. How a page persists its own changes

[[[appendices.settings-pages#persisting-changes]]]

There is no generic persistence layer in the dialog shell — persisting is entirely each page's own
job, via whatever `save_changes()` does. `DescriptionsPage`'s flow is the concrete pattern to
follow for a new staged-edit page:

1. `__sync_current_css_draft()` folds the visible CSS editor's text into whichever draft slot
   (`__markdown_css_draft`/`__mistletoe_css_draft`) matches the currently-selected engine radio —
   the two engines' CSS stay independent even though they share one editor widget.
2. The staged values (engine, both CSS drafts, image-width) are written onto the shared
   `MarkdownRenderingSettings` singleton (§5 below).
3. `settings.save(persistent_settings())` writes the now-current values to the on-disk `QSettings`
   ini.

`ExcludedFilesPage` adds a fourth step to that flow, because saving can *change* what it saved: blank and
duplicate patterns are dropped, and an emptied list resolves back to the shipped defaults
([[data-model#checksums]]). It therefore reloads itself from the saved set afterwards — a page still
showing what was typed would disagree with what every scan actually reads, which is the same
one-predicate discipline the field locks follow. A page whose `save_changes()` normalizes owes the user
the normalized result on screen.

`ImagesPage`'s extension block does the same, over the same `StringListEditor`, and the two are worth
reading side by side because **what each of them normalizes is different**: a *pattern* is matched
verbatim, so only blanks and duplicates go; a *format* also loses its leading dot and its casing, so
`BMP` comes back `.bmp`. Both rules live on the settings object, never in the widget — the widget holds
what was typed, which is what lets one editor serve two blocks that disagree (#231).

It also lost a Default/Custom radio pair in the same slice, whose flag said which half was in effect. The
pair went because the empty-list fallback already draws that distinction — a list naming nothing *is*
"whatever this app ships", and the editor's Reset fills the list with that set on request. The old keys
are simply not read: an installation that had set a custom list gets the shipped formats back and sets it
again, which was the cheaper trade than carrying a compatibility path for a preference two clicks deep.

`RegistryPage` has no local settings dataclass at all: Register/Unregister write straight to the
Windows registry via `rehuco_agent.windows_registration` when clicked, so there is nothing left for
`save_changes()` to do.

## 4. Adding a new settings page

[[[appendices.settings-pages#adding-a-page]]]

- One `.ui` + one `.py` per page, flat under `rehuco_agent/settings/ui/` (no further subdirectory —
  matches the one-file-per-unit convention already used for `fields/*.py`).
- Implement `SettingsPage` structurally: an ordinary `.ui`-backed `QWidget` subclass
  ([[appendices.code-conventions]]), no base class to inherit.
- Register it in `MainWindow.__register_settings_pages` via `self.__settings_dialog.add_page(...)`
  — the *first* page added becomes the initially-selected one. Pass `group="..."` to nest it under a
  category group ([[appendices.settings-pages#category-groups]]); leave it off for a top-level row.
- A platform-gated page (like `RegistryPage` — "System Integration", Windows-only) is imported
  lazily inside the `if sys.platform == "win32":` branch, and takes whatever app-level data it needs
  (e.g. `ARCHIVE_EXTENSIONS`) as a constructor parameter rather than importing it back from
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
  control that should grow (e.g. `DescriptionsPage`'s CSS editor), stretch that frame's layout
  item so it — not the spacer — takes the slack when shown, while the spacer keeps a lone remaining
  frame top-aligned. Set that stretch in the controller after `setupUi()` (`main_layout.setStretch`),
  not in the `.ui`: the current `pyside6-uic` mistranslates a box-layout `stretch` property. A page adds
  no scroll area of its own — `add_page` already gives it one, handing it the viewport's width and as
  much height as it asks for (§Overview).
- Use `StringListEditor` (`borco_pyside.widgets`) to edit a list of strings, rather than building a list
  and a column of buttons by hand — or, worse, a comma-separated `QLineEdit`, which cannot hold a value
  containing the separator and makes changing one entry mean retyping the lot (#231). It is the list plus
  two action columns: insert/edit/delete/reset and top/up/down/bottom, each with a key (`Ins`, `F2`,
  `Del`, `Ctrl+Home`/`Up`/`Down`/`End`), armed on the view alone so an open in-place editor keeps its own
  `Del`. `with_ordering=False` (or `set_ordering_visible`) hides the ordering half for a list whose order
  carries nothing. It ships **no icons**: call `apply_string_list_editor_icons`
  (`rehuco_agent/string_list_editor_icons.py`) to dress it in this app's set, and set its `defaults` to
  whatever Reset should restore. It holds what was typed and normalizes nothing — that stays on the
  settings object, where two pages can (and do) normalize differently (§3).
- Use `ContentSizedListView` (`borco_pyside.widgets`) for any *other* list, not a plain `QListView`
  (`StringListEditor` already uses one inside, over a `QStringListModel`). A list
  that scrolls inside a page that scrolls gives two vertical scrollbars and a list the reader has to
  scroll *to* before they can scroll *in*; this one is sized to its rows (one row as the floor) and lets
  the page's scroll area do the scrolling (#229).
- Use `WrappingLabel` (`borco_pyside.widgets`) for a paragraph of explanatory text, not a `QLabel` with
  `wordWrap` on. A plain wrapping `QLabel` hints as though its text were one wide line, and the frame
  around it is sized from that hint — so the paragraph paints past the border (#226, fixed in #229).

## 5. Making the rest of the app react to a saved change

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
value on every use. Not every block needs this at all — `ImagesPage`'s extension list is read
only when an enumeration runs, and `ExcludedFilesPage`'s pattern list only when a size scan or a checksum
run does, so a plain dataclass carries each and there is nothing to watch either change;
`RegistryPage`'s actions land directly on the OS, so there is no other part of the app that needs to be
told a save happened.

**Testing note:** the `lru_cache`d singleton persists across test functions within one process, and
would otherwise leak state between tests (or read the developer's real on-disk settings) — see the
autouse `isolate_shared_markdown_rendering_settings` fixture in
`packages/rehuco-agent/tests/conftest.py`, which clears the cache and mocks `persistent_settings()`
around every test. A new page with its own shared settings object needs the equivalent, reactive or
not — `isolate_shared_image_viewer_settings` is the second reactive one, and
`isolate_shared_identity_settings` / `isolate_shared_reference_images_settings` /
`isolate_shared_excluded_files_settings` the plain-dataclass
counterparts, all sitting right beside it.
