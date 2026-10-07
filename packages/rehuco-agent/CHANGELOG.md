# Changelog

All notable changes to `rehuco-agent` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`rehuco-agent` only, and its releases are tagged `rehuco-agent-X.Y.Z`. The section for the version being
released becomes the body of the GitHub Release, so each entry is written to be read there on its own.

## [Unreleased]

### Added

- The Roots view shows **the checksum state of the files a checksum record covers**. A file's row has an icon at
  the right edge of its column -- matching, not matching, no checksum, and an old, faded one when the check has
  expired or was made at another location -- and a file that did not match has its name in red. The details pane
  shows the same icon beside the file's name, and a **Checksum** row with the verdict and a **Last check** row with
  the date, how long ago -- or *expired*, or *at another location*. A file is read from its own record: `foo.checksum` for a
  `foo.rehu`, otherwise the folder's `info.checksum`, whose subfolders are covered too. A picture of an image file
  is now shown below the pane's buttons. A checksum file's default action is now **Verify old checksums**, which
  leaves a valid check alone and records the files that have none; **Verify checksums** checks every file. A
  screenshot no longer offers to create a rehu of its own. `Root Catalog` > **Automatically preview the current
  rehu**, also a Root Catalog settings page, switches off the Roots view driving the Documents preview. A checksum file's verify entries no longer go dead after a verify or a Refresh relists its folder (the pane rebuilt its buttons while the listing was still being diffed in and found no rehu beside the file). **Verify checksums** from the Roots view reports what it found on its row in
  the Tasks panel, in the document banner's words, and the rows update when it ends.
- The Root Catalog's **Roots view** is a column view: the first column lists the `.rehuco`'s roots and each further
  one a folder's contents, listed when you open it and never while it would block a rename. **Add Root** asks what
  the folder lives on before the folder. The selected root's **name** and **storage** are edited in the pane beside the columns
  — a local folder, a network share, a removable drive or a CD or DVD, each with its own icon. A root that cannot be
  listed says so: a deleted local folder is struck through, and a share, drive or disc that is away keeps its icon
  greyed out. Remove Root asks first and says how many cached entries go. A root's right-click menu has the folder filter and Open in file
  explorer, then the moves, then Remove Root, and a root's row shows its folder under its name. A checksum file's menu
  has **Verify checksums**. A folder's has **Show only rehu in this folder**, which filters the current browser.
  `F5` lists the open columns again, a folder deleted outside the app disappears, and the selection falls back to
  the nearest folder that is left. Roots are reordered by dragging the grip at the left of a root's row, as well as from its menu; the grip
  only shows while the catalog can be saved and says *Drag to reorder* when hovered. A dragged root behaves as a
  dragged location does: it leaves its place, and one shadow shows where it will land, the other roots closing up
  around it. A rename the app makes shows in the columns without a reload. A pane beside
  the columns shows the details of the selected row -- a root, a folder or a file, with a thumbnail for an image --
  and a button for every entry of the row's right-click menu, which now also has **Open in file explorer** on a
  root or folder. Double-clicking runs a row's default action, the bold first entry of its right-click menu:
  a `.rehu` or `.tc` file or a folder with a rehu opens in Documents, any other file opens in its own application. A
  folder's or file's menu says **Open associated rehu** or **Create info.rehu** (or **Create <name>.rehu**) by
  whether it has one, and a double-click never creates.
- A **Root Catalog** panel beside Documents, first on the action bar and closed until a `.rehuco` is opened, when
  it and the Browsers panel both show. Each has its own entry in `View`, and closing one leaves the other.
  `Root Catalog` > `New…`, `Open…` and `Open Recent` open one file at a time, as
  does double-clicking a `.rehuco` in a file manager, and the one left open is reopened on start under its own Session
  page toggle, beside the documents'. Its roots can be
  added and removed from the `Root Catalog` menu, whose **Scan** puts one task-queue job per root that records the
  `.rehu` and uncovered `.tc` files
  found into a `.rehudb` cache in the local cache folder, and a table lists what the cache holds. A rescan reads
  only the files that changed since the last one. Double-clicking
  a row opens that resource in Documents. A `.rehuco` written by a newer build opens read-only. Neither panel has a
  toolbar: the Root Catalog's title bar holds Refresh and the Browsers' New Table Browser, and the rest is in the
  menus.
- The menu bar is five short menus, each about one thing: `File` (open and close documents, the open list,
  Settings, Quit), `Root Catalog`, `Browsers`, `View` and `Tools`. `File` and `Browsers` each list what is open, A–Z,
  with the focused one checked, and picking an entry brings it to the front; `View` no longer lists documents. `Sweep checksums…`,
  `Import Legacy Catalog…` and `Conversion Backups…` moved to `Tools`. Remove Root is also on a root's right-click
  menu.
- **Table browsers** in a **Browsers** panel of their own, beside the Root Catalog one and named like its menu:
  add as many as you like with **New Table Browser**, on the panel's title bar and in `Browsers`, each with its
  own name, columns and sort. **Rename** and **Clone** (the copy starts with the same columns) are on the browser's
  title bar and its tab's right-click menu, and `Browsers` > `Rename Browser…` renames the current one; the [x]
  deletes a browser.
  A table browser has a column for every field the cache holds: authors, title, type, path, publisher, URL, tags,
  release date, size, last update, a tutorial's three durations and its level, a reference pack's claimed and
  measured image counts, and **Format**: the file's format version, `tc` for a legacy `.tc`, and `?` for a `.rehu`
  not read since this version (a scan fills it in). The URL and the tutorial and reference-pack columns start
  hidden; the header's right-click menu shows and hides any column, and each browser remembers its choice.
  New Table Browser's menu also starts a browser from a preset: **Tutorial Columns** or **Reference Images Columns**
  shows that type's columns and lists only resources of that type. Sizes,
  durations and counts sort as numbers, and a cell with nothing in it sorts as the smallest value -- first ascending,
  last descending -- so one click on a header brings the rows lacking a value to the top (#466); hovering a size
  shows its exact bytes. Rows can be multi-selected. A rename, save or deletion made in the app changes just the
  rows it touched, keeping the selection and the sort, instead of reloading the table. Each
  catalog remembers its browsers and where they sit between runs, on this machine only. New icons for the
  roots and browser actions.
- A **filter line** over each table browser: free text plus `field:value` or `field:"quoted value"` tokens for
  `folder`, `authors`, `tags`, `publishers` and `type`, all of which must match. The rows narrow as you pause
  typing, or at once on Enter. The status line under the table counts what is shown and adds up its sizes and, for
  reference packs, its image counts, saying how many rows each total leaves out as unmeasured and how many are
  legacy `.tc` files, and after them, for the rows selected, how many there are and their sums by the same rule; the
  line shortens the selection first and holds the whole text as its tooltip; a `folder` token matches the root label ignoring ASCII case and the path beneath it as the
  filesystem does. An unknown field is flagged with a warning icon on the line, and the rest of the line still
  applies. Each browser remembers its line.
- Author names in a document's viewer are links: clicking one brings the Root Catalog forward with
  `authors:"<name>"` set on its current browser, opening a browser if none is open. Right-clicking an **Authors**
  cell in a table browser offers the same for each of the row's authors, and offers to clear the filter by one the
  line already holds; the rest of the line is kept.
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

- The current card of a document's **Locations** field is no longer filled in the selection blue: its add and delete
  buttons, shown for as long as it is current, mark it.
- A root's **Removable** checkbox is gone: what a root lives on is its **storage**, chosen when it is added and
  changed on the card under the Roots view. A `.rehuco` saved by this build is read-only in an earlier one, and a
  catalog no longer remembers the Roots table's column widths.
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

### Fixed

- A checked, unsaved document in the `File` menu no longer touches its title in the Fusion style: the entry reserves
  two more pixels beside its marks.
- Right-clicking a table browser's header could stop showing the column menu until the app was restarted. The menu
  no longer holds on to the header it was built for, and a menu that cannot open is logged once instead of raised.
- Clearing a table browser's filter line, with its clear button or otherwise, could leave the filtered rows on screen:
  an error showing the line's problem marker stopped the rows from being read again. The rows are read first now, and
  the marker is found again each time instead of being held on to. A line edit sometimes showing two clear buttons
  (the filter line and the Location fields among them) is fixed too.

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
