# rehuco-agent

[![PyPI](https://img.shields.io/pypi/v/rehuco-agent)](https://pypi.org/project/rehuco-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/rehuco-agent)](https://pypi.org/project/rehuco-agent/)

*PySide6 desktop GUI for [rehuco](https://borco.github.io/rehuco/): open, view, and edit `.rehu` files.*

[View on PyPI](https://pypi.org/project/rehuco-agent/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Early — `0.0.x`.** The editor works: it opens a `.rehu`, shows and edits its fields, and saves.
The `.rehu` format is still moving and there is no upgrade guarantee between `0.0.x` releases yet, so
keep backups of anything you point it at. See [GitHub Issues](https://github.com/borco/rehuco/issues)
for what's in progress.

## What it is

`rehuco-agent` is [rehuco](https://borco.github.io/rehuco/) itself, as far as anything you can run
goes: a desktop editor for the `.rehu` sidecar that describes one resource. Tested on Windows, macOS,
and Linux.

![The rehuco-agent editor: fields on the left, rendered viewer on the right](https://raw.githubusercontent.com/borco/rehuco/master/docs/assets/images/rehuco-agent.png)

- **Single-instance launcher** — double-click a `.rehu` file to open it in the running instance
- **Viewer and editor** — common fields, a Markdown description, and the resource's screenshots as a
  thumbnail strip with a click-to-maximize lightbox
- **Editing that saves atomically** — with unrecognized fields left untouched, and a file from a newer
  format version opened read-only rather than rewritten
- **Legacy `.tc` conversion** — read the predecessor format and write `.rehu`, keeping backups
- **A workspace that persists** — per-file panel layout and session restore

## Goals

`rehuco-agent` aims to be:

- **MIT licensed** — usable in open-source or closed-source projects freely
- **PySide6 native** — built on Qt via PySide6 and the pyqtads docking framework
- **Single-instance** — one running app per user; additional launches forward their arguments in

## Installation

```bash
pip install rehuco-agent
```

PySide6 6.9+ is installed automatically as a dependency.

## License

[MIT](https://github.com/borco/rehuco/blob/master/LICENSE)
