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
    def is_dirty(self) -> bool: ...
    def save_changes(self) -> None: ...
    def drop_changes(self) -> None: ...
```

**A page does not name itself** (#277). It used to carry a `title` property, which put the tree's
labels in a dozen classes that each knew only themselves, so no single place could be read — or
sorted — to see what the tree would look like. `add_page` takes the title instead, in two overloads:

```python
def add_page(self, title: str, page: SettingsPage, /) -> None: ...
def add_page(self, group: str, title: str, page: SettingsPage, /) -> None: ...
```

Positional, in that order, so a run of registrations reads the way the tree does and sorts as plain
lines of text. The dialog stores the title on the row itself (`TITLE_ROLE`), apart from the row's
displayed text, which can carry a dirty badge ([[appendices.settings-pages#dirty-state-ui]]) — so
everything that has to *recognize* a row rather than draw it reads that role instead of unpicking a
prefix.

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
`SettingsDialog.add_page(title, page)`; the dialog itself lives inside a floating-first, dockable
`DockableDialog` on the outer `CDockManager` (#47's dockable-dialog framework — out of scope here).

## 1. The category tree (#76, #277)

[[[appendices.settings-pages#category-groups]]]

**Today the tree is one flat list, in alphabetical order** (#277): "Checksums" (`ChecksumsPage`, #242),
"Descriptions" (`DescriptionsPage`), "Excluded Files" (`ExcludedFilesPage`, #226), "Identity"
(`IdentityPage`, #99), "Images" (`ImagesPage`), "Legacy Screenshots" (`LegacyScreenshotsPage`, #53),
"Logs" (`LogsPage`, #200), "Session" (`SessionPage`, #65), "System Integration", "Tasks"
(`TasksPage`, #202) and "Videos" (`VideosPage`, #225).

"System Integration" is one page on every platform with a different class behind each (`RegistryPage`
on Windows, `DesktopIntegrationPage` on Linux, and `SystemIntegrationPage` on macOS, which registers
nothing because the association comes from the app bundle) — all three sharing that one title, which is
why all three registrations sit at the same point in the order. macOS has that page at all only because
the tray block lives on it (#205): a setting deciding what the window's close button does has to be
reachable wherever there is a window.

**The order is the registration order**, not a rule the dialog applies: `add_page` appends, and
`MainWindow.__register_settings_pages` makes its calls alphabetically — platform pages included, each
`if sys.platform` block sitting at its own page's position rather than after everything else. Ordering
that a caller can see and change beats a `QSortFilterProxyModel` layer over the existing filter proxy,
which would also complicate the current-row and restore-on-show paths (#228, #230) to take the decision
away from the one place that has the context to make it.

**There is no group in use, and the machinery for one is kept** (#277). Until #277 the four pages a
resource type owns — Descriptions, Excluded Files, Images, Videos — nested under a **Plugins** group
row. What that bought was a word the reader has to know before they can look under it: "Videos" is
findable by its own name, and "Plugins" only hides it behind an implementation term. So they were
promoted to top-level rows. The `group=` parameter and everything behind it (below) stay: a settings
tree may want a tier again, and a working, tested one is worth more dormant than rebuilt.

The test a top-level row passes is that a reader looking for it has no plugin name to guess. Checksums
govern every resource type and the sweep that reads them is reached from `File` rather than from a
document, so filing them under a plugin would hide them behind a word the reader never thought of.
Legacy screenshot rules pass it the same way (#53): converting a `.tc` happens to a resource of any
type, and the import wizard that reads them is reached from `File` as well.

**One page per subject, not per owner.** "Images" gathers every image-shaped setting whichever object
owns it: the viewer surface and thumbnail strips (`ImageViewerSettings`), the width cap on an image
embedded in a description (`MarkdownRenderingSettings`), and which archive entries a reference-images
resource counts as its images (`ReferenceImagesSettings`, #222). The last two arrived from elsewhere —
the cap was a block on Descriptions, the extension list a "Reference Images" page holding nothing but
that list. Both were filed where the *code* owned them, so finding either meant knowing which plugin
or settings object to look under, when what the reader had was the word "images". A page whose one
block is a list is also a tree row that costs a click to learn it holds one thing.

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
`isolate_settings_dialog_settings` fixture in `packages/rehuco-agent/tests/rehuco_agent_tests/conftest.py` patches the
dialog's `persistent_settings()` — otherwise any test building one (directly, or via `MainWindow`)
would read and overwrite the developer's real settings file, and leak toggle state into later tests.

### The group tier, retained but unused (#277)

Nothing calls for a group today; all of this stays working and tested, for the next tree that wants a
tier. The tree is **two levels deep at most**: `add_page("Plugins", "Videos", page)` nests the page's
row under that group's row, creating the group's row on first use; the two-argument
`add_page("Videos", page)` — what every caller uses now — leaves it a top-level row of its own. Group
names are plural: a group holds pages.

A group row **carries no page of its own** — it is a header. Selecting it shows everything under it at
once, in one scrolling column, each page's contribution under its own title as a heading — since the
tree selection no longer names what you are looking at once several pages are shown together (#230).

**The column takes blocks, not pages** (`SettingsBlockColumn`, `settings/ui/settings_block_column.py`).
The block — a page's top-level labelled `QFrame`, the same unit the filter shows and hides — is the
row here, and a page is simply the view that shows its own blocks when its own row is selected. Two
things fall out of that which the alternative had to be patched into:

- **A heading follows its blocks.** A page the filter empties contributes nothing, so there is no
  heading left standing over a gap promising settings that filtered out. `sync_headings` shows a
  heading exactly while some block under it is visible.
- **Nothing spreads.** A page's layout is written for being shown alone — zero margins, a trailing
  spacer, and sometimes one block stretched to fill what is left ([[appendices.settings-pages#adding-a-page]]).
  Carrying whole pages into the column brought all of that with them: each page's spacer claimed a share
  of the height and pushed the pages apart, and the stretch had to be argued back down with a size
  policy. Taking only the blocks leaves that layout where it is right — on the page's own view — and the
  column supplies the single trailing stretch itself.

So **a block fills when alone and packs when it isn't**, without either view knowing about the other:
`DescriptionsPage` stretches its engine block so the CSS editor fills the page, and in a group column
that same block takes its natural height. The dialog reads that stretch once at registration
(`__record_blocks`) and re-applies it when the block comes home, because a box layout keeps stretch per
item and a widget taken out leaves its factor behind.

A block has one parent, so moving between the two views is always a move, never a copy. Everything
that walks pages (Save all / Drop all, and Save/Drop *current page* on a selected group row) recurses
one level into groups, so a grouped page is never skipped.

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
  `ExcludedFilesPage`, "Excluded Files"; `VideosPage`, "Videos") — edits live in
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
- **Mixed pages** ("System Integration") — its registration buttons (Register/Unregister) already took
  effect on the OS the moment they were clicked, so nothing of *theirs* is ever staged; the tray checkbox
  beside them (#205) is staged like any other control. `is_dirty()`/`save_changes()`/`drop_changes()`
  therefore answer for the tray block alone. The page was purely immediate-effect until #205 merged Tray
  into it, which is what turned a page that could never be dirty into one that can.

`is_dirty()` is what drives all of the dialog's dirty-state UI — the tree badges, the Apply/Reset
enablement, and auto-apply ([[appendices.settings-pages#dirty-state-ui]]).

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

`VideosPage` reloads itself after saving for the same reason, over the same rule: its video-extension
list normalizes exactly as the reference-images one does, and the two share it
(`settings/extension_lists.py`) rather than each restating a rule that differs only in which set an
emptied list falls back to. Its other block is the **duration probe** ([[field-schema#duration-size]]),
which adds two things neither list page needs. First, **each backend's own settings are stored side by
side** — an `engine` key naming a registry member, and `ffprobe_executable` kept whether or not ffprobe
is the selected backend — so switching to MediaInfo and back does not lose a path that was typed; that is
the `markdown_css`/`mistletoe_css` arrangement, and the page keeps both halves too, disabling the path
row under the other backend rather than hiding or clearing it. An `engine` naming a backend this build
does not have (an `.ini` written by a newer version) selects the default rather than raising, the way
`ImageViewerSettings` already treats an unrecognized `mode`. Second, **the page reports whether the
selected backend can actually run**, asking the probe itself (`unavailable_reason`) about the *staged*
choice as it is typed: a scan under an unusable backend raises rather than measuring `0`
([[field-schema#duration-size]]), so an ffprobe path pointing at nothing has to be visible here rather
than surfacing as a row that refuses to compute.

The "System Integration" pages have no local settings dataclass of their own: Register/Unregister write
straight to the OS when clicked (`rehuco_agent.windows_registration` on Windows), so the registration half
leaves `save_changes()` nothing to do. What it does save is the tray checkbox, through `TrayBlock`
(`settings/ui/tray_block.py`, #205) into the shared `TraySettings`.

`TrayBlock` is **not a widget**, which is the part worth knowing: the block itself is a plain `QFrame`
declared in each of the three pages' own `.ui`, because `SettingsFrameFilter` counts only exact-`QFrame`
direct children of the page as blocks and deliberately excludes subclasses
([[appendices.settings-pages#category-groups]]) — a `TrayBlock(QFrame)` widget would have been invisible to
the filter, the group column and the dirty highlight alike. So the markup is duplicated per page and only
the behavior is shared, which is the half that reads and writes persistent storage and therefore the half
where three copies would drift into a real defect rather than a cosmetic one.

## 4. Dirty-state UI: badges, highlight, auto-apply (#77)

[[[appendices.settings-pages#dirty-state-ui]]]

`is_dirty()` is consumed at two granularities the dialog derives without any page-specific wiring:

- **Page level** — `SettingsDialog` reads a page's own `is_dirty()`. A dirty page's category-tree row
  is prefixed with `DIRTY_DOCK_MARKER` (`documents/document_dock.py`), the same glyph a dirty document
  tab uses, so the two affordances read as one idiom. Apply/Reset (current page and all) are enabled
  only while there is something for them to act on: current-page actions track `is_dirty()` of the
  selected row's page(s), the "all" actions track whether *any* registered page is dirty.
- **Frame level** — no page reports this; `SettingsPage.is_dirty()` only ever answers for the whole
  page. `SettingsFrameFilter` derives it generically instead: it snapshots every frame's recognized
  control values (`QLineEdit`, `QPlainTextEdit`, `QAbstractButton`, `QSpinBox`, `StringListEditor`) at
  construction, and `dirty_frames()` compares the live values against that snapshot.
  `resync_baseline()` adopts the current values as the new clean state — the dialog calls it right
  after every `save_changes()`/`drop_changes()`, or `dirty_frames()` would keep comparing against the
  *previous* clean state and report a just-settled page as still dirty. This snapshot approach needs no
  per-page changes and matches what every staged-edit page's own `is_dirty()` already checks, with one
  accepted gap: `DescriptionsPage` keeps the *other* engine's CSS draft off-widget while its own is
  shown, invisible to a widget-only snapshot — harmless, since the highlight is a visual aid and
  `is_dirty()` stays the badge/enablement source of truth.

A dirty frame gets a low-alpha pink background (`DIRTY_BACKGROUND`, `fields/colors.py`) -- a visual
aid only, naming nothing to click. The mechanics are the field toolkit's own `WARNING_STYLESHEET`
idiom: every block wears a `QFrame[dirty="true"]` property-selector stylesheet
(`DIRTY_FRAME_STYLESHEET`) from registration, and toggling the `dirty` dynamic property (plus an
unpolish/polish) is all that turns the tint on and off -- behind a changed-guard, so the poll leaves
unchanged frames entirely alone instead of re-parsing a stylesheet per tick. A background-only rule,
deliberately: it composes with the native `StyledPanel` border, so a dirty frame keeps the platform
look, where any QSS `border` rule would replace the OS-drawn panel wholesale. An earlier
version of this slice also floated a per-frame `SettingsFrameOverlay` with its own Apply/Reset buttons
in each dirty frame's corner; it was removed (#77) because those buttons could only ever act on the
**whole page** (nothing generic can tell which settings field a widget maps to, so a true per-frame
partial commit isn't derivable from the widgets alone), and a page with several dirty frames at once
showed several Apply/Reset pairs that all did the same whole-page thing -- reading as scoped to the
frame they sat in when they weren't. The toolbar's own Apply/Reset is the one true way to commit or
discard a page's changes.

A dialog-wide **"Apply changes as they're made"** `WrappingCheckBox` drives auto-apply: while checked,
a page found dirty on the next poll tick is committed immediately. It lives in the toolbar, added via
`toolbar.addWidget()` in `__init__` rather than the `.ui` -- Designer has no way to drop a plain widget
onto a `QToolBar` (only actions), so it's built in code the same way `ImageLightbox`'s own overlay
chrome is.

All of this is driven by a `QTimer` poll (`DIRTY_POLL_INTERVAL_MS`, 200 ms), started in `showEvent` and
stopped in `hideEvent` — nothing here needs to react faster than a human notices, and a poll is simpler
than wiring a change signal through every field-widget type each page happens to use. The dialog also
refreshes once synchronously after every `add_page` and after every toolbar commit, so the visible
state never waits a whole tick to catch up with an explicit action.

**Dirty-marker identity note:** a tree row's *displayed* text carries the badge, but its identity
(what `restore_selected_page`/`save_filter_state` compare and persist) is the title `add_page` was
given, kept on the row under `TITLE_ROLE` ([[appendices.settings-pages#overview]]) — so nothing has to
strip a marker back off the text to recognize a row (#277).

## 5. Adding a new settings page

[[[appendices.settings-pages#adding-a-page]]]

- One `.ui` + one `.py` per page, flat under `rehuco_agent/settings/ui/` (no further subdirectory —
  matches the one-file-per-unit convention already used for `fields/*.py`).
- Implement `SettingsPage` structurally: an ordinary `.ui`-backed `QWidget` subclass
  ([[appendices.code-conventions]]), no base class to inherit.
- Register it in `MainWindow.__register_settings_pages` via
  `self.__settings_dialog.add_page("Its Title", ItsPage())` — **at its alphabetical position among the
  existing calls**, since registration order is tree order
  ([[appendices.settings-pages#category-groups]]). The page itself declares no title, and nothing uses
  the grouping overload today. The
  *first* page registered is the initially-selected one.
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
- A control offering **one choice per entry of a registry core owns** is built in the page's `__init__`
  from that registry, into an empty mount widget declared in the `.ui` — `ChecksumsPage`'s algorithm
  radios over `CHECKSUM_ALGORITHMS` (#242) are the first. Hand-listing them in the `.ui` drifts silently
  the moment core edits its set, and an algorithm added there would simply be unofferable. **Build them
  before the page is registered**: `SettingsFrameFilter` gathers a frame's searchable text once, at
  `add_page`, so a control created later is invisible to the filter. A `__init__`-built control is fine;
  one built on first show is not.
- Use `StringListEditor` (`borco_pyside.widgets`) to edit a list of strings, rather than building a list
  and a column of buttons by hand — or, worse, a comma-separated `QLineEdit`, which cannot hold a value
  containing the separator and makes changing one entry mean retyping the lot (#231). It is the list plus
  two action columns: insert/edit/delete/reset and top/up/down/bottom, each with a key (`Ins`, `F2`,
  `Del`, `Ctrl+Home`/`Up`/`Down`/`End`), armed on the view alone so an open in-place editor keeps its own
  `Del`. `with_ordering=False` (or `set_ordering_visible`) hides the ordering half for a list whose order
  carries nothing. It ships **no icons**: call `apply_item_action_icons`
  (`rehuco_agent/item_action_icons.py`) to dress it in this app's set, and set its `defaults` to
  whatever Reset should restore. It holds what was typed and normalizes nothing — that stays on the
  settings object, where two pages can (and do) normalize differently (§3). It is a `QStringListModel`
  under `ItemListEditor`, the shared machinery the `authors` record rows are built on too (#97), which is
  why a list edited on a settings page and one edited in a document behave identically.
- Use `ContentSizedTableView` under `ItemListEditor` for a list whose entries are **more than one
  field**, rather than packing them into one string with a separator. `LegacyScreenshotsPage`'s rules —
  a cover and a template per row (#53) — are the worked example: a small `QAbstractTableModel` over the
  domain objects supplies the columns, and everything about *how* the list is edited still comes from
  `ItemListEditor`, so it behaves exactly as a `StringListEditor` does. Override the editor's
  `row_is_blank` when a row is only abandonable with *every* cell empty; the base reads the first column
  alone, which would discard an insert somebody had typed a second field into. `AuthorsListEditor`
  (#97) is the same construction in a document field.
- Use `ContentSizedListView` (`borco_pyside.widgets`) for any *other* list, not a plain `QListView`
  (`StringListEditor` already uses one inside, over a `QStringListModel`). A list
  that scrolls inside a page that scrolls gives two vertical scrollbars and a list the reader has to
  scroll *to* before they can scroll *in*; this one is sized to its rows (one row as the floor) and lets
  the page's scroll area do the scrolling (#229).
- Use `WrappingLabel` (`borco_pyside.widgets`) for a paragraph of explanatory text, not a `QLabel` with
  `wordWrap` on. A plain wrapping `QLabel` hints as though its text were one wide line, and the frame
  around it is sized from that hint — so the paragraph paints past the border (#226, fixed in #229).

## 6. Making the rest of the app react to a saved change

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
only when an enumeration runs, `ExcludedFilesPage`'s pattern list only when a size scan or a checksum
run does, and `LegacyScreenshotsPage`'s rules only when a `.tc` is scanned or converted, so a plain
dataclass carries each and there is nothing to watch any of them change;
`RegistryPage`'s actions land directly on the OS, so there is no other part of the app that needs to be
told a save happened.

**Testing note:** the `lru_cache`d singleton persists across test functions within one process, and
would otherwise leak state between tests (or read the developer's real on-disk settings) — see the
autouse `isolate_shared_markdown_rendering_settings` fixture in
`packages/rehuco-agent/tests/rehuco_agent_tests/conftest.py`, which clears the cache and mocks `persistent_settings()`
around every test. A new page with its own shared settings object needs the equivalent, reactive or
not — `isolate_shared_image_viewer_settings` is the second reactive one, and
`isolate_shared_identity_settings` / `isolate_shared_reference_images_settings` /
`isolate_shared_excluded_files_settings` / `isolate_shared_legacy_screenshots_settings` /
`isolate_shared_videos_settings` the plain-dataclass counterparts, all sitting right beside it.
