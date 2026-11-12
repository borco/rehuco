# rehuco-core

[![PyPI](https://img.shields.io/pypi/v/rehuco-core)](https://pypi.org/project/rehuco-core/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/rehuco-core)](https://pypi.org/project/rehuco-core/)

*Shared library for [rehuco](https://borco.github.io/rehuco/): data models, `.rehu` file I/O, checksums, a catalog
cache, and a task queue.*

[View on PyPI](https://pypi.org/project/rehuco-core/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Alpha.** It does real work: it is what the desktop app reads and writes files with, in daily use. But
it is developed for that one consumer, the file formats still change between releases, and the API changes without
notice. The [release milestones](https://github.com/borco/rehuco/milestones) say what ships next.

## What it is

`rehuco-core` is the non-GUI half of [rehuco](https://borco.github.io/rehuco/): everything the desktop
editor needs to read and write a resource's `.rehu` sidecar, with no Qt dependency.

It provides:

- **Data models** — the `.rehu` document, its common fields, and per-type plugin blocks
- **File I/O** — atomic read and write, with unknown fields preserved verbatim
- **Format versioning** — a per-file version, migrations applied on load, and read-only handling of a
  file written by a newer version
- **Per-user state** — one user's ratings, flags, learning paths and watch progress for a resource, in a
  `.rehuser` sidecar of its own beside the `.rehu`
- **Content checksums** — a `.checksum` record beside the `.rehu` holding, per content file, its hash,
  when it was last verified and what the answer was; generate and verify read it, and can re-check just
  one file or skip whatever was checked recently
- **Content enumeration** — which files a resource covers, the images inside a reference pack's
  archives, and measured size on disk and video duration
- **A catalog** — the `.rehuco` file listing folder roots, each a `.rehuroot` file of its own that catalogs share, a
  root's path layouts rendered per record, and the `.rehudb` SQLite cache of the records found under them: an
  incremental scan, targeted updates after a save or rename, and filtered reads
- **Staged images** — an image taken out of a resource, written unchanged under a name that traces it back
- **A task queue** — one long job at a time, pausable, cancellable, reorderable, optionally persisted
  across restarts
- **Legacy `.tc` conversion** — parsing the predecessor format and converting it to `.rehu`, one file or
  a whole folder tree, with backups and rollback

## Goals

`rehuco-core` aims to be:

- **MIT licensed** — usable in open-source or closed-source projects freely
- **Dependency-light** — no GUI dependencies; installable on headless servers and low-spec NAS hardware
- **Typed** — fully annotated public API with a `py.typed` marker for type-checker integration

## Installation

```bash
pip install rehuco-core
```

## License

[MIT](https://github.com/borco/rehuco/blob/master/LICENSE)
