# Changelog

All notable changes to `rehuco-agent` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`rehuco-agent` only, and its releases are tagged `rehuco-agent-X.Y.Z`. The section for the version being
released becomes the body of the GitHub Release, so each entry is written to be read there on its own.

## [Unreleased]

### Added

- A **Root Catalog** panel beside Documents, first on the action bar and closed until a `.rehuco` is opened.
  `Root Catalog` > `New…`, `Open…` and `Open Recent` open one file at a time, as
  does double-clicking a `.rehuco` in a file manager, and the one left open is reopened on start under its own Session
  page toggle, beside the documents'. Its roots can be
  added and removed, **Scan** puts one task-queue job per root that records the `.rehu` and uncovered `.tc` files
  found into a `.rehudb` cache in the local cache folder, and a table lists what the cache holds. A rescan reads
  only the files that changed since the last one. Double-clicking
  a row opens that resource in Documents. A `.rehuco` written by a newer build opens read-only.
- The menu bar is six short menus, each about one thing: `File` (Settings, Quit), `Root Catalog`, `Documents`,
  `Browsers`, `View` and `Tools`. `Documents` and `Browsers` each list what is open, A–Z, with the focused one
  checked, and picking an entry brings it to the front; `View` no longer lists documents. `Sweep checksums…`,
  `Import Legacy Catalog…` and `Conversion Backups…` moved to `Tools`. Add Root and Remove Root moved from the
  Root Catalog toolbar to the Roots list's title bar, and Remove Root is also on a root's right-click menu.
- **Table browsers** in the Root Catalog panel: add as many as you like with **New Table Browser**, each with its
  own name, columns and sort. **Rename** and **Clone** (the copy starts with the same columns) are on the browser's
  title bar and its tab's right-click menu, and the toolbar renames the current one; the [x] deletes a browser. The Roots list can now be hidden with its [x] and shown with the toolbar's **Roots** toggle. Each
  catalog remembers its browsers and where its sub-docks sit between runs, on this machine only. New icons for the
  roots and browser actions.
- A **filter line** over each table browser: free text plus `field:value` or `field:"quoted value"` tokens for
  `folder`, `authors`, `tags`, `publishers` and `type`, all of which must match. The rows narrow as you pause
  typing, or at once on Enter, and the status line counts what is shown. `columns:authors,title` picks the columns
  shown; showing or hiding one from the header's right-click menu rewrites the token. An unknown field or column is
  flagged with a warning icon on the line, and the rest of the line still applies. Each browser remembers its line.
- Author names in a document's viewer are links: clicking one brings the Root Catalog forward with
  `authors:"<name>"` set on its current browser, opening a browser if none is open.
- A **Shortcuts** page in Settings: search every command by name, description or key, click a key and
  press its replacement (the numeric keypad and a lone Esc included), give a command several keys, and
  choose where its keys reach. Recording a key another command uses asks whether to reassign it. The table
  sorts by any column, and the search text and sort are remembered.
- **Ctrl+Shift+M** maximizes the focused document's current dock, and restores it, as its tab button does.
- Save, Maximize current dock and the two Refresh commands can be set to **Focused document, app-wide** on the
  Shortcuts page: their key then acts on the focused document from anywhere in the app, the Log dock and
  floating docks included.
- The **Content Images** panel and the measured image count include a reference pack's loose images, not
  only those inside its archives. Folders and archives sort together, ignoring case, the pack's own
  folder first. Both honour the Files page's excluded-files globs, as checksums do.

### Changed

- The Session page's one restore check is two: **Opened root catalog** and **Opened documents**, under *Restore
  on restart*. Each decides only its own half of what comes back on start; a setting saved with the old single
  check carries over to both.
- Every text box's clear button is the style's plain × instead of the backspace glyph, and a duration's looks
  the same. The Shortcuts page's search box no longer shows two.
- Every keyboard shortcut is now read from the settings file's `shortcuts` group, falling back to its
  default, so a changed key reaches every open window and document. The defaults are unchanged.
- The Save and Refresh buttons' tooltips name their keys.
- Content Images banners name every folder the same way, by its path under the pack with an archive as one
  more folder: `/`, `foo/`, `foo.zip/`, `foo.zip/bar/`. The status line and the viewer's info overlay
  spell an image's path the same way (`foo.zip/bar/a.jpg`). The two banner boxes are now one, **Show
  banners**, and *Hide a top folder named like its zip* follows it; a saved choice carries over, banners
  on if either old box was. Inside an archive, a folder's images come before its subfolders'.
- An image named by a legacy screenshot pattern (`01.jpg`, `cover.jpg`, ...) is content: the Files panel
  lists it as such, and checksums, size on disk and duration include it. Beside the `.rehu` it is still
  offered for conversion in the Images panel. The screenshot name patterns setting no longer affects
  checksums or measurements. The next verify of an existing `.checksum` adopts such files as unexpected.
- What the app does to files shows at once in every place that shows them, without a rescan. When a resource is
  renamed, an open document stored inside it is re-pointed too: a member of a renamed collection folder, or a
  `.rehu` in a renamed folder. The Root Catalog table follows renames, saves and conversions. The Files panel
  follows renames, saves, conversions, screenshot reorders, deletions and drops, and finished checksum runs. It
  keeps the selection and scroll position, and stays in the same subfolder after a rename or a conversion.

## [0.2.0] - 2026-09-27

### Added

- Each resource type shows only its own fields; a reference pack gains an image count.
- A **Content Images** panel on reference packs: the images inside the pack's archives, in a grid that
  opens any of them in the maximized viewer.
- Size on disk, video duration and image count can be measured from the content and applied on request.
- **Checksums**: generate and verify a resource, sweep a whole folder, a per-resource Checksums panel,
  legacy `.sfv`/`.md5`/`.sha*` manifests adopted, and trust tracked per location.
- A **Tasks** panel running long jobs one at a time — pause, cancel, reorder, kept across restarts — with
  a status-bar indicator and each job's own log.
- A **Log** panel for the app and one per resource.
- **Import Legacy Catalog**: bulk `.tc`→`.rehu` conversion over a folder tree, plus a Conversion Backups
  manager to discard the backups it keeps.
- **Web scraping**: drop a URL on the editor to fill it from ArtStation, Udemy or your own scraper script;
  a dropped HTML selection lands in the description as Markdown; `--scrape` and `--scrape-schema` on the
  command line.
- Screenshots can be moved, deleted (to the Recycle Bin) and converted from the Images panel; the
  screenshot name patterns are a setting.
- A **Files** panel over the resource's folder, and Reveal in the system's file browser.
- Location name templates per resource type, with replacements.
- A tray icon, off by default: closing hides to the tray, and Quit is explicit.
- Panels can be hidden, pinned to a window sidebar, or maximized in their tab; the default layout is
  saved per resource type.
- `Ctrl+W` closes the current document, with Close Missing and Close All beside it; the View menu marks
  the focused and unsaved documents.
- Table editors for authors, collections and learning paths.
- Windows crash dumps can be switched on from System Integration, and every run is recorded in a
  rotating log file.

### Changed

- Settings is a regular panel that reopens if it was open at exit (its "Restore on start" option is
  gone), returns to the last page shown, marks unsaved pages, and has many new pages.
- Screenshots open maximized on a double-click instead of a single click; the viewer's background is
  opaque and its buttons show on hover.
- The Image Previews toggle hides every image, including the Content Images grid and images in a
  description.
- Session restore can be switched off, and a restored document is read only when its tab is first shown.
- Switching document tabs is about twice as fast.
- Toolbar icons recolor at once on a theme switch.

### Fixed

- The unsaved-changes prompt names the document instead of `info.rehu`.
- After a rename, the document tab, the window title and Open Recents show the new name.
- An unconverted `info.tc` gets its folder's name on its tab, like an `info.rehu`.
- Converting a `.tc` keeps each screenshot's number, and swaps its Open Recents entry for the new `.rehu`.
- Relative paths given to a second launch are resolved before being handed to the running instance.
- Oversized or deeply nested `.rehu`/`.tc` files are refused instead of exhausting memory.

### Known limitations

- `.avif` images count as content images but do not display.
- The installers are still neither code-signed nor notarized.

## [0.1.1] - 2026-07-29

The first release to reach PyPI, so `pip install rehuco-agent` and `uv tool install rehuco-agent` now get
the application instead of the `0.0.1` name-reservation stub that had been sitting there. The application
is byte-for-byte what `0.1.0` shipped — no fixes, no new behaviour, and the installers attached here are
rebuilt from the same sources. What is new is the publishing path itself.

### Changed

- The PyPI project page now shows a screenshot of the editor, and describes the package's maturity
  without naming a version series that goes stale at the next bump.

## [0.1.0] - 2026-07-29

The first release built from this repository, and the first to ship a working application rather than a
stub — published to exercise the release plumbing end to end rather than because the app is ready to be
depended on. It starts a new minor series because `0.0.0` and `0.0.1` were spent on PyPI name-reservation
stubs that contained no application.

### Added

- Edits a resource's details from a `.rehu` file: title, authors, publisher, release date, URL, durations,
  sizes, rating, level, tags, flags, and a Markdown description.
- Shows a resource's screenshots in a strip beside the fields, with arrow-key and wheel navigation, and
  control over which images the strip shows.
- Converts legacy `.tc` catalogs to `.rehu`, keeping backups it can roll back if a conversion goes wrong.
- Leaves unrecognized fields untouched across a save, and opens a file written by a newer format version
  read-only rather than rewriting it.
- Saves atomically, and remembers each file's panel layout between sessions.
- Registers as the `.rehu` handler on Windows and Linux, from the app or via `--register`/`--unregister`;
  `--version` and `--info` report the version and the current registration.
- Ships installers for Windows (`.msi`), macOS (`.dmg`) and Linux (`.AppImage`).

### Known limitations

- The installers are neither code-signed nor notarized, so Windows SmartScreen and macOS Gatekeeper warn on
  first run and have to be overridden by hand.
- On Windows the packaged executable is a GUI-subsystem binary and prints nothing to a console, so
  `--version` and `--info` report through their exit code there; a source checkout prints normally.

## [0.0.1] - 2026-06-30

Second name-reservation stub on PyPI, published a day after `0.0.0` and still carrying no application.

## [0.0.0] - 2026-06-29

Name-reservation stub, published to PyPI so the name could not be taken by anyone else. Neither this
release nor `0.0.1` was built from this repository — when both were uploaded the repository contained no
Python packages at all, so there is no source in the history that corresponds to them.
