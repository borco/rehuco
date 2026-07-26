# rehuco

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![QA](https://github.com/borco/rehuco/actions/workflows/qa.yml/badge.svg)](https://github.com/borco/rehuco/actions/workflows/qa.yml)
[![Coverage](https://img.shields.io/badge/Coverage-blue)](https://codecov.io/gh/borco/rehuco)
[![Windows](https://img.shields.io/codecov/c/github/borco/rehuco?flag=windows&label=Windows)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=windows)
[![macOS](https://img.shields.io/codecov/c/github/borco/rehuco?flag=macos&label=macOS)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=macos)
[![Linux](https://img.shields.io/codecov/c/github/borco/rehuco?flag=linux&label=Linux)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=linux)

| Package | Version | Downloads | Python |
| --- | --- | --- | --- |
| [rehuco-core](https://pypi.org/project/rehuco-core/) | [![PyPI](https://img.shields.io/pypi/v/rehuco-core)](https://pypi.org/project/rehuco-core/) | [![Downloads](https://static.pepy.tech/badge/rehuco-core)](https://pepy.tech/project/rehuco-core) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-core)](https://pypi.org/project/rehuco-core/) |
| [rehuco-node](https://pypi.org/project/rehuco-node/) | [![PyPI](https://img.shields.io/pypi/v/rehuco-node)](https://pypi.org/project/rehuco-node/) | [![Downloads](https://static.pepy.tech/badge/rehuco-node)](https://pepy.tech/project/rehuco-node) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-node)](https://pypi.org/project/rehuco-node/) |
| [rehuco-agent](https://pypi.org/project/rehuco-agent/) | [![PyPI](https://img.shields.io/pypi/v/rehuco-agent)](https://pypi.org/project/rehuco-agent/) | [![Downloads](https://static.pepy.tech/badge/rehuco-agent)](https://pepy.tech/project/rehuco-agent) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-agent)](https://pypi.org/project/rehuco-agent/) |
| [borco-core](https://pypi.org/project/borco-core/) | [![PyPI](https://img.shields.io/pypi/v/borco-core)](https://pypi.org/project/borco-core/) | [![Downloads](https://static.pepy.tech/badge/borco-core)](https://pepy.tech/project/borco-core) | [![Python](https://img.shields.io/pypi/pyversions/borco-core)](https://pypi.org/project/borco-core/) |
| [borco-pyside](https://pypi.org/project/borco-pyside/) | [![PyPI](https://img.shields.io/pypi/v/borco-pyside)](https://pypi.org/project/borco-pyside/) | [![Downloads](https://static.pepy.tech/badge/borco-pyside)](https://pepy.tech/project/borco-pyside) | [![Python](https://img.shields.io/pypi/pyversions/borco-pyside)](https://pypi.org/project/borco-pyside/) |

Every package is at an early `0.0.x` — published so the names are taken and the release plumbing is
exercised, not because they are ready to depend on.

## What it is

A personal media catalog for the things you collect to learn from and work with — video tutorials,
online courses, archives of reference images. Today it is the part that comes first: a desktop editor
for a resource's **details**, not for the media itself.

Those details live in a small JSON file — a `.rehu` — sitting in the folder next to the resource it
describes, one per resource. That's the whole storage model, and the name is its stem.

**[How it works](docs/specs/how-it-works.md)** is one page on the whole system as it stands: the file,
the rules that keep it trustworthy, the app's panels, and what isn't built.

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

Self-describing by design: because the details sit next to the content, reading a resource needs
nothing but the folder it's in — no index to build first, no server, no account.

Tested on Windows, macOS, and Linux.

## Where it's going

The **editor plus a basic browser** is the part worth finishing: the remaining editor work (a
reference-images resource type, a log dock and task queue, tray and preferences), and then a view
over a folder of resources — a rebuildable cache with search, so a collection can be looked through
rather than opened one file at a time. See the
[implementation plan](docs/specs/implementation-plan.md).

Past that point the design reaches further — playback with progress tracking, a headless node with a
REST API, sync and offline borrowing between machines, multi-user access rules, a browser interface,
Daz3D library migration. None of it is implemented, none of it is scheduled, and some of it may never
be: it is what the architecture is shaped to allow, and each piece has to earn its place when its
turn comes. The [design specs](docs/specs/README.md) explore that territory in depth — as intent, not
as a description of the current build.

Maintenance is tracked separately in **audit-run milestones** `X1`, `X2`, … — each collects the
issues found during the N-th codebase audit.

## Monorepo layout

```text
rehuco/                       # uv virtual-workspace root (no [project] table)
├── packages/
│   ├── borco-core/           # generic non-GUI utilities — temporary guest, moving out
│   ├── borco-pyside/         # generic PySide widgets/utilities — temporary guest, moving out
│   ├── rehuco-core/          # shared models, .rehu I/O, field types, legacy .tc reading
│   ├── rehuco-agent/         # PySide6 desktop GUI — the viewer/editor
│   └── rehuco-node/          # a reserved name; no service written yet
├── docs/specs/               # design specs (see the document map)
└── tools/                    # repo tooling (mkdocs hooks, slug checker)
```

`rehuco-agent` is the desktop GUI and the only runnable program here; `rehuco-core` is the library it
reads and writes files with. `rehuco-node` holds a name and a version constant against the day a
headless service is written — nothing imports it, and nothing depends on it existing.

## File formats

| Extension | Purpose | Status |
| --- | --- | --- |
| `.rehu` | Per-resource sidecar (JSON). Source of truth. | implemented |
| `.rehuco` | Per-machine config: folder roots, mounts, ownership flags, plugin list. | reserved, not written |
| `.rehudb` | SQLite catalog cache. Derived; rebuildable. | reserved, not written |
| `.rehusw` | Swarm state: membership, users + salted hashes, access rules. Durable. | reserved, not written |

`.tc`, the format of the [tutcatalog](#history) predecessors, is read for conversion only — rehuco
never writes it.

## History

| Project | Host | First Commit | Last Commit | Commits | Duration | Language | Qt |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [ibocator](https://sourceforge.net/projects/ibocator/) | SourceForge | 2010/01/26 | 2010/07/19 | 427 | 3 months | C++ | Qt4 |
| [tutcatalog](https://gitlab.com/iborco-software/tutcatalog/tutcatalog) | GitLab | 2016/08/09 | 2020/09/30 | 743 | 4 years | C++ | Qt5 |
| [tutcatalog (v3)](https://gitlab.com/iborco-software/tutcatalog/tutcatalog3) | GitLab | 2017/05/02 | 2017/05/29 | 81 | 1 month | C++/Python | Qt5 |
| [tutcatalogpy](https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy) | GitLab | 2020/08/19 | 2021/01/28 | 407 | 6 months | Python | Qt5 |
| [TutCatalogPy2](https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy2) | GitLab | 2021/06/01 | 2022/01/04 | 392 | 7 months | Python | Qt5 |
| [daz3d-personal-database](https://gitlab.com/iborco-software/daz3d/daz3d-personal-database) | GitLab | 2022/01/01 | 2023/11/11 | 754 | 1 year 10 months | Python | Qt6 |
| [tutcatalogpy3](https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy3) | GitLab | 2022/02/07 | 2022/07/28 | 205 | 6 months | Python | Qt6 |
| [tutcatalog4](https://gitlab.com/iborco-software/tutcatalog/tutcatalog4) | GitLab | 2022/09/19 | 2024/12/22 | 519 | 2 years 3 months | C++/Python | Qt6 |
| [daz3d-personal-database-2](https://gitlab.com/iborco-software/daz3d/daz3d-personal-database-2) | GitLab | 2023/05/10 | 2023/09/16 | 1053 | 4 months | Python | Qt6 |
| [tutcatalog5](https://gitlab.com/iborco-software/tutcatalog/tutcatalog5) | GitLab | 2024/12/22 | 2025/04/15 | 408 | 4 months | Python | Qt6 |
| [resource-hub](https://gitlab.com/iborco-software/tutcatalog/resource-hub) | GitLab | 2026/04/27 | 2026/06 | 449 | 2 months | Python | Qt6 |
| **rehuco** | GitHub | 2026/06 | present | | | Python | Qt6 |

GitHub mirrors:
[tutcatalog (v3)](https://github.com/borco/tutcatalog) ·
[TutCatalogPy2](https://github.com/borco/TutCatalogPy2)

## License

[MIT](LICENSE)
