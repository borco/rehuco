# Changelog

All notable changes to `borco-pyside` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`borco-pyside` only, and its releases are tagged `borco-pyside-X.Y.Z`.

## [Unreleased]

### Added

- `QtAdsLayout`: saves a `CDockManager`'s layout as a JSON-able tree of splitters, tabbed areas, floating windows
  and sidebars, and restores it by moving the manager's own docks into place. Each part restores on its own: a dock the
  tree names that the manager lacks is skipped, or built by a `create_dock` hook; a dock the tree does not name goes
  to a `place_unnamed` hook; a malformed node is dropped. A hook stores each dock's content state in its entry and
  hands it back on restore.
- `ReorderDrag`, `drop_slot` and `paint_drag_ghost`: what a list reordered by dragging shows while an item is
  dragged -- the item leaves its place, one shadow stands where it would land and the other items close up around it --
  shared by the card list and any item view that reorders its rows the same way.
- `QtAdsLoneTabHider`, which hides the tab of a dock with title-bar actions while it is alone in a floating window --
  QtAds keeps such a dock's title bar for its buttons, and the tab with it, naming the window a second time -- and
  shows it again once another dock joins or the dock docks.
- `QtAdsTabContextActions`, which puts a dock's own actions at the top of its tab's right-click menu, above QtAds'
  *Detach* and *Close* and set apart by a separator, for the docks it is given and no others.
- `RowBandDelegate`, which paints a selected row as one band with padded text instead of a box per cell.
  `ItemListEditor` installs it on its view.
- `borco_pyside.shortcuts`: shortcuts as declared `Command`s with a scope and an optional focus group, a
  `Keymap` of the user's overrides stored under a settings group, `find_conflicts`, and a
  `CommandRegistry` that binds live actions to commands and re-keys every one of them when the keymap
  changes. A host installs one registry for generic widgets to bind through. A `BindingRole.ROUTER` action
  carries a command's keys app-wide while its scope is `CommandScope.DOCUMENT_APP_WIDE` and its instances
  carry none, so one key is never on two actions; `bound_actions` filters by role.
- `HeaderSectionsMenu`, a context menu on a `QHeaderView` with one checkable action per section to show or
  hide it (the last visible one stays), sections made movable, and `save_state()` / `restore_state()` over
  the header's own state; a state that fails to restore leaves every section shown. Its
  `sections_visibility_changed` signal says when the menu or a restore showed or hid a section.
- `LIST_EDITOR_COMMANDS`, `CARD_LIST_COMMANDS` and `LOG_COMMANDS`, the commands behind the list editor's,
  the card list's and the log view's keys, for a host to register.

### Changed

- `LogFilterModel.search` matches every word of the search, in any order, a `"quoted run"` as one phrase, ignoring case
  and diacritics (`borco_core.TextMatcher`), where it matched the whole text as one case-insensitive substring.
- The current card of a card list is no longer filled and outlined in the selection colour: it is painted like any
  other card, and its add and delete buttons, shown for as long as it is current, are its only mark. `CardStyle`
  ships no `CURRENT` state and `CardStyle.style_for` takes the card's states alone; a flagged card shows its state's
  fill and border whether or not it is current.
- The list-editor, card and log-view actions take their keys from the installed `CommandRegistry` when
  there is one; with none installed they keep their keys as before. `set_tooltip_and_shortcut` and
  `ActionButtonColumn.add_action` take an optional `command_id`.
- `ItemListEditor` abandons a freshly inserted blank row when the user *leaves* it (the current row moves,
  or focus goes outside the view) rather than when its first editor closes, and a row counts as blank only
  while every editable cell is, so a row can be filled in any order. Cancelling the first editor, and any
  close on a one-column list, still abandon it at once. An edit to another row while a blank insert waits
  is now reported.
- `LineEditClearActionFilter` draws its clear action with the style's own clear-button icon instead of a glyph,
  and leaves alone a line edit that turned Qt's clear button on; it takes only an optional parent, the glyph, font
  family and colour role arguments gone.

### Fixed

- `CardListEditor` finds a card's tab-order widgets among the card's own descendants instead of walking the window's
  focus chain. `nextInFocusChain()` registers each widget it returns as a child of the wrapper it was called on, so the
  walk hung every Qt-made widget's wrapper in the window from the card's, and deleting the card invalidated them all
  while the widgets lived on.
- `QtAdsFloatingShowGuard.release` no longer fails with "already deleted" when a floating window was shown in the
  middle of a QtAds call: the guard keeps no wrapper of the windows it holds and finds them again when released.
- `force_foreground` restores a window only when it is minimized. It restored every window, which took a maximized
  or snapped one back to its normal size and position. The restore is `restore_if_minimized`, which a window's own
  show path can call too: the native restore is the one route back from a minimize that keeps a snap, where Qt's
  `showNormal()` drops it.
- Pinning a dock that has a `QtAdsPinSideHandler` no longer invalidates the Python wrappers of objects Qt made
  inside that dock while the objects still exist, which made them raise "already deleted" on next use. The
  handler now asks the dock for its slide-out container rather than asking the container for its dock: that
  call registered the dock under a wrapper that was discarded as the pin finished.
- `LineEditClearActionFilter` could equip a line edit with a second clear button when the Python wrapper of the first
  was invalidated while the action itself lived on. It now keeps no reference to its action and finds it on the line
  edit by object name, so there is only ever one; `LineEditClearActionFilter.action_of(line_edit)` is how.
- `ActionIconThemeHandler` raised "already deleted" from `resync_companion_checked_state` once the wrapper of the
  action it was given was invalidated while the action lived on. Parented to the action (the default), it now reads
  the action back from its parent each time.

## [0.2.0] - 2026-09-27

### Added

- `borco_pyside.logging` — an in-app log viewer: `LogBridge` caches records and replays them to any
  number of scoped `LogModel`s, shown by `LogView`/`LogWidget` with level filtering.
- `StringListEditor` and `ItemListEditor` for editing lists and tables with insert/delete/reorder
  actions.
- QtAds helpers: a per-tab maximize toggle, sidebar pinning that remembers each dock's side, a guard
  against floating docks showing before the main window, and safe dock removal.
- `RecycleBin` — move files to the Recycle Bin/Trash, refusing instead of deleting permanently where no
  bin exists.
- `reveal_in_file_browser` — show a path in Explorer, Finder or the Linux file manager.

### Changed

- Themed icons pick their color while painting, so every window agrees after a theme switch.
- Requires `pyside6-qtads` 5.0.0.2 or later.

### Fixed

- `ElidedLabel` no longer HTML-escapes plain text.
- `UnboundedSpinBox` no longer reverts valid input such as `+5` or `007` while typing.
- `ApplicationSingleton` no longer hands its arguments to an unrelated instance when a failed rebind
  falls back to its previous name.
- `MessageBanner` no longer flashes a discarded row as a stray window.
- A line edit's clear action no longer crash-loops after its action is deleted.

## [0.1.0] - 2026-07-29

`ApplicationSingleton` was the whole package through `0.0.2`; everything below joined it since.

### Added

- Theming — a theme manager cycling follow-system/light/dark, a theme model and menu, an
  application-palette-change notifier, glyph-based action icons, and SVG recolouring.
- Dockable dialogs — `CDockWidget`-hosted dialog panels that can be restored on start, with their own
  frame, manager and settings.
- Widgets — elided label, flow layout, rating, rich-text view, message banner, unbounded spin box,
  wrapping check box, horizontal line, line-edit clear action, and layout/dynamic-property helpers.
- QtAds helpers — a focus tracker and widget wrappers.
- `borco_pyside.core` — property helpers and a connection list.
- Windows window activation.

## [0.0.2] - 2026-07-01

### Changed

- README now links to the PyPI project and the GitHub repository. No functional change — the released
  code is identical to `0.0.1`.

## [0.0.1] - 2026-07-01

Initial release, published to reserve the name on PyPI.

### Added

- `ApplicationSingleton` (`borco_pyside.core.application_singleton`) — a single-instance guard built on
  `QLocalServer`/`QLocalSocket`: the first process serves, later ones forward their argv to it and exit.
  Moved here out of the desktop app so it could be reused.
