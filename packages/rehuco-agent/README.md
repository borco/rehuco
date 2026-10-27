# rehuco-agent

[![PyPI](https://img.shields.io/pypi/v/rehuco-agent)](https://pypi.org/project/rehuco-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/rehuco-agent)](https://pypi.org/project/rehuco-agent/)

*PySide6 desktop GUI for [rehuco](https://borco.github.io/rehuco/): open, view, and edit `.rehu` files.*

[View on PyPI](https://pypi.org/project/rehuco-agent/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Early.** The editor works: it opens a `.rehu`, shows and edits its fields, and saves.
The `.rehu` format is still moving and there is no upgrade guarantee between releases yet, so
keep backups of anything you point it at. See [GitHub Issues](https://github.com/borco/rehuco/issues)
for what's in progress.

## What it is

`rehuco-agent` is [rehuco](https://borco.github.io/rehuco/) itself, as far as anything you can run
goes: a desktop editor for the `.rehu` sidecar that describes one resource, and a browser over the folders that hold them. Tested on Windows, macOS,
and Linux.

![The rehuco-agent editor with a reference-images resource open: edit fields and a read-only viewer alongside description, checksums, content images, files, and an app-wide log dock](https://raw.githubusercontent.com/borco/rehuco/master/docs/assets/images/rehuco-agent--documents.png)

![The Root Catalog panel's column view of a root's folders with a details pane for the selected item, above a Browsers panel listing the catalog's records in a filterable table](https://raw.githubusercontent.com/borco/rehuco/master/docs/assets/images/rehuco-agent--browser-and-root-catalog.png)

- **Single-instance launcher** — double-click a `.rehu` file to open it in the running instance
- **Viewer and editor** — common fields, a Markdown description, and the resource's screenshots as a
  thumbnail strip with a click-to-maximize lightbox
- **Editing that saves atomically** — with unrecognized fields left untouched, and a file from a newer
  format version opened read-only rather than rewritten
- **Legacy `.tc` conversion** — read the predecessor format and write `.rehu`, keeping backups
- **A workspace that persists** — per-file panel layout and session restore
- **Root catalog and browsers** — open a `.rehuco` naming your folders, scan them into a cache, and browse it
  in filterable tables, with a column view of the folders and a preview of whatever is selected
- **Follows the disk** — a record added or edited outside the app is read into the catalog without a Scan, and an
  open document says when its file changed
- **Plays a tutorial's videos** — double-click one in the Files panel: seek bar, speed, keyboard, previous and
  next through the whole tutorial, and it opens on the video you watched last, paused where you stopped
- **Images out to other apps** — drag or copy an image from the app into a file manager, an image editor or a browser
- **Rebindable shortcuts** — a Shortcuts page in Settings, with conflict detection
- **Task queue** — background jobs (checksum sweeps, `.tc` imports, conversions) run through a
  queue dock with per-job progress, state, and log
- **Log dock** — an app-wide log and a per-resource log, both filterable
- **Settings** — a docked Settings page for checksums, images, identity, scrapers, the Root Catalog, and more
- **System tray** — an optional tray icon that closes the window to the tray instead of quitting

## Goals

`rehuco-agent` aims to be:

- **MIT licensed** — usable in open-source or closed-source projects freely
- **PySide6 native** — built on Qt via PySide6 and the pyqtads docking framework
- **Single-instance** — one running app per user; additional launches forward their arguments in

## Installation

```bash
pip install rehuco-agent
```

Requires Python 3.14+; PySide6 6.9+ is installed automatically as a dependency. Windows, macOS and Linux installers
are attached to each [GitHub release](https://github.com/borco/rehuco/releases).

## License

[MIT](https://github.com/borco/rehuco/blob/master/LICENSE)
