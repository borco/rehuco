# Changelog

All notable changes to `rehuco-agent` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`rehuco-agent` only, and its releases are tagged `rehuco-agent-X.Y.Z`. The section for the version being
released becomes the body of the GitHub Release, so each entry is written to be read there on its own.

## [Unreleased]

### Added

- A **Content Images** panel on every reference-images document, hidden by default: the images inside
  the pack's archives, in rows justified to the panel's width and in natural order, each archive opening with a
  banner naming it and counting its images. A banner click folds its images away and a second click
  brings them back; the banner of the group being scrolled through stays pinned at the top. A click
  selects an image and a status line under the grid names it, or the one under the pointer; the arrow
  keys move the selection, `+`/`-` fold the current group, `Esc` clears it. Read-only,
  since those images live in a checksummed archive. Thumbnails decode off the interface thread as they
  scroll into view; nothing is written to disk.
- Double-clicking a content image opens it maximized in the same viewer screenshots use, navigating the
  whole pack. The viewer's `I` key (or its corner button) shows the image's name, pixel size and file
  size in a corner overlay, hovering a thumbnail names it in a box right above the row (no tooltip
  delay), `T` toggles the thumbnail row, and a double-click on the image closes it. A screenshot is
  named relative to the `.rehu`, the way an archive member is.
- Holding a key while double-clicking picks the viewer's surface for that one open, whatever Images /
  Display says: `Shift` for the document overlay, `Ctrl` for the app-window overlay, `Ctrl+Shift` for
  full screen.
- Images / Display gains the Content Images row-height clamp and two banner boxes — zip file names,
  folder names in zips — plus the viewer's info overlay, its background colour, whether a double-click
  closes it and whether closing it selects the image it was on back in the panel (scrolled into view,
  its group expanded), all applied live to open panels and viewers.

### Changed

- A document's panels are the common set plus what its type adds — today the Content Images panel on a
  reference pack — and the **default layout is saved per type**: *Save current layout as default for
  Tutorial* and *Reset default layout for Tutorial* name the type they act on, and a type with no default
  opens as built. A document restored with the session keeps the layout that was stored for it; one opened
  fresh gets its type's default; changing a document's type in the editor leaves its panels and layout as
  they are, and the layout button then applies the new type's default. The previous single default layout
  is dropped. Saved layouts survive a panel being added to one type: a layout now restores onto a document
  whose panels differ from the ones it was saved with.
- The maximized viewer paints an opaque background (the dark grey code editors use, configurable) instead
  of dimming the document underneath, and its close, thumbnail-row and info buttons appear only while the
  pointer is near them, like the prev/next bands.
- Screenshots in a document's strip open maximized on a double-click, not a single click.
- The app-wide *Image Previews* toggle (`Ctrl+Shift+`\`) now hides every image: the Content Images panel
  keeps only its banners, and a description's embedded images stand in as `[image: name]` placeholders.
- The maximized viewer's thumbnail row decodes lazily, only what is in view, so it opens as fast over a
  pack of thousands as over three screenshots.
- `.avif` still counts as a content image but does **not** decode in the shipped Qt plugin set (`webp`
  does): such members show as a broken placeholder in the panel rather than an image.

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
