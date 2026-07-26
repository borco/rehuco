# rehuco

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![QA](https://github.com/borco/rehuco/actions/workflows/qa.yml/badge.svg)](https://github.com/borco/rehuco/actions/workflows/qa.yml)
[![Coverage](https://img.shields.io/badge/Coverage-blue)](https://codecov.io/gh/borco/rehuco)
[![Windows](https://img.shields.io/codecov/c/github/borco/rehuco?flag=windows&label=Windows)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=windows)
[![macOS](https://img.shields.io/codecov/c/github/borco/rehuco?flag=macos&label=macOS)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=macos)
[![Linux](https://img.shields.io/codecov/c/github/borco/rehuco?flag=linux&label=Linux)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=linux)

rehuco is a desktop editor for `.rehu` files — JSON sidecars that describe one resource (a video
tutorial, an online course, an archive of reference images) and sit next to it on disk.

## What it does

- **Edits a resource's details.** Open a `.rehu` from the file manager or from the app: title,
  authors, publisher, release date, URL, durations, sizes, rating, level, tags, flags, and a Markdown
  description.
- **Shows its screenshots.** A thumbnail strip beside the fields — click one to fill the window,
  arrow keys or the wheel to move through the set, and pick which of them the strip shows.
- **Converts legacy `.tc` catalogs.** Reads the older format, writes `.rehu`, and keeps backups it
  can roll back if the conversion goes wrong.
- **Doesn't damage what it doesn't understand.** Unrecognized fields survive a save untouched, and a
  file written by a newer version of the format opens read-only rather than being rewritten.
- **Keeps your workspace.** Atomic saves, and each file's panel layout remembered between sessions.

Self-describing by design: a `.rehu` sits next to the content it describes, so reading a resource's
details needs nothing but the file itself — no index, no server, no account.

Tested on Windows, macOS, and Linux.

## Where it's going

The **editor plus a basic browser** is the part worth finishing: the remaining editor work (a
reference-images resource type, a log dock and task queue, tray and preferences), and then a view over
a folder of resources — a rebuildable cache with search, so a collection can be looked through rather
than opened one file at a time. See the [implementation plan](specs/implementation-plan.md).

Past that point the design reaches further — playback with progress tracking, a headless node with a
REST API, sync and offline borrowing between machines, multi-user access rules, a browser interface,
Daz3D library migration. None of it is implemented, none of it is scheduled, and some of it may never
be: it is what the architecture is shaped to allow, and each piece has to earn its place when its turn
comes. The [design specs](specs/README.md) explore that territory in depth — as intent, not as a
description of the current build.

Maintenance is tracked separately in **audit-run milestones** `X1`, `X2`, … — each collects the issues
found during the N-th codebase audit.

## rehuco packages

rehuco is published as three separate packages on PyPI, all at an early `0.0.x` — published so the
names are taken and the release plumbing is exercised, not because they are ready to depend on.

| Package | Description | PyPI | Downloads | Python |
| --- | --- | --- | --- | --- |
| [rehuco-agent](https://pypi.org/project/rehuco-agent/) | PySide6 desktop GUI | [![PyPI](https://img.shields.io/pypi/v/rehuco-agent)](https://pypi.org/project/rehuco-agent/) | [![Downloads](https://static.pepy.tech/badge/rehuco-agent)](https://pepy.tech/project/rehuco-agent) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-agent)](https://pypi.org/project/rehuco-agent/) |
| [rehuco-core](https://pypi.org/project/rehuco-core/) | Shared library: models, `.rehu` I/O, legacy `.tc` reading | [![PyPI](https://img.shields.io/pypi/v/rehuco-core)](https://pypi.org/project/rehuco-core/) | [![Downloads](https://static.pepy.tech/badge/rehuco-core)](https://pepy.tech/project/rehuco-core) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-core)](https://pypi.org/project/rehuco-core/) |
| [rehuco-node](https://pypi.org/project/rehuco-node/) | A reserved name; no service written yet | [![PyPI](https://img.shields.io/pypi/v/rehuco-node)](https://pypi.org/project/rehuco-node/) | [![Downloads](https://static.pepy.tech/badge/rehuco-node)](https://pepy.tech/project/rehuco-node) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-node)](https://pypi.org/project/rehuco-node/) |

## Generic libraries (temporarily hosted)

Two generic, reusable libraries under the author's `borco` namespace are **not rehuco-specific**. They are
developed in this monorepo for now and will later move to their own repository. If you install them from PyPI,
that move is handled automatically.

| Package | Description | PyPI | Downloads | Python |
| --- | --- | --- | --- | --- |
| [borco-core](https://pypi.org/project/borco-core/) | Generic reusable classes with no GUI dependency | [![PyPI](https://img.shields.io/pypi/v/borco-core)](https://pypi.org/project/borco-core/) | [![Downloads](https://static.pepy.tech/badge/borco-core)](https://pepy.tech/project/borco-core) | [![Python](https://img.shields.io/pypi/pyversions/borco-core)](https://pypi.org/project/borco-core/) |
| [borco-pyside](https://pypi.org/project/borco-pyside/) | Generic reusable PySide6/Qt classes (e.g. `ApplicationSingleton`) | [![PyPI](https://img.shields.io/pypi/v/borco-pyside)](https://pypi.org/project/borco-pyside/) | [![Downloads](https://static.pepy.tech/badge/borco-pyside)](https://pepy.tech/project/borco-pyside) | [![Python](https://img.shields.io/pypi/pyversions/borco-pyside)](https://pypi.org/project/borco-pyside/) |
