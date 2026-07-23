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

A personal, distributed catalog for tutorials, references, and creative assets.
The name is the stem of the file formats it owns: `.rehu`, `.rehuco`, `.rehudb`, `.rehusw`.

## What it is

rehuco manages a large, heterogeneous personal media collection spread across multiple machines —
local video tutorials, online course registrations, zip archives of reference images, Daz3D plugins,
3D objects, and more. Each resource is described by a `.rehu` (JSON) sidecar file alongside it. The system
adds a distributed node model and supports offline use, multi-user access control, and a web
interface for tablet access.

Key design properties:

- **Self-describing data.** `.rehu` files live next to the content they describe. The SQLite cache
  (`.rehudb`) is rebuildable from `.rehu` files; it is a cache, never the source of truth.
- **No single always-on machine.** The system is a swarm of peer nodes, each capable of answering
  for itself, each tolerant of any other node being unreachable.
- **Offline-first.** Borrowing a resource onto a laptop and watching it without any network
  connection is a first-class use case.

## Roadmap

The build is organized into milestones, each mapping to a personal use-case and adding one new
architectural spine. See the [implementation plan](docs/specs/implementation-plan.md) for detail.

| Milestone | What it does |
| --- | --- |
| **LocalEdit** *(current)* | Local viewing and editing of `.rehu` files — one machine, no network, no login. |
| **CacheDB** | Scan folders, cache the scan results into a `.rehudb` database, and search the catalog. Brings the app close to the original tutcatalog. |
| **WatchTutorial** | Watch tutorials locally, or from a browser/tablet via an embedded web server, with progress remembered. |
| **Borrowing** | Borrow a copy onto a laptop, watch it offline, and reconcile progress and notes on return — two-party sync (home node ↔ laptop), the minimal reconcile topology. |
| **Swarm** | The full multi-node swarm — peer discovery, pairing and trust, registry resolution, and N-way sync across many machines. |
| **Daz3D** | Migrate from the daz3d-personal-database predecessor — import and browse `.dpdml` files, and install/uninstall Daz3D plugins/extensions. |

Maintenance is tracked separately in **audit-run milestones** `X1`, `X2`, … — each collects the
issues found during the N-th codebase audit. Acquisition tooling and richer reference-image plugins
remain deferred beyond the milestones above.

## Monorepo layout

```text
rehuco/                       # uv virtual-workspace root (no [project] table)
├── packages/
│   ├── borco-core/           # generic non-GUI utilities — temporary guest, moving out
│   ├── borco-pyside/         # generic PySide widgets/utilities — temporary guest, moving out
│   ├── rehuco-core/          # shared models, .rehu I/O, field types, sync primitives
│   ├── rehuco-agent/         # PySide6 desktop GUI — tray, viewer/editor, catalog/admin UI
│   └── rehuco-node/          # headless REST service (FastAPI + uvicorn)
├── docs/specs/               # design specs (see the document map)
└── tools/                    # repo tooling (mkdocs hooks, slug checker)
```

`rehuco-agent` is the PySide6 desktop GUI; it is a node client for swarm operations.
`rehuco-core` is a shared library.
`rehuco-node` is the headless service (FastAPI + uvicorn); it runs on capable hardware and mounts
the NAS share — the QNAP TS-230 is storage, not a compute host. Getting the node to run directly
on the NAS would be a nice bonus if it ever proves workable, but nothing depends on it.

## File formats

| Extension | Purpose |
| --- | --- |
| `.rehu` | Per-resource sidecar (JSON). Source of truth. |
| `.rehuco` | Per-machine config: folder roots, mounts, ownership flags, plugin list. |
| `.rehudb` | SQLite catalog cache. Derived; rebuildable. |
| `.rehusw` | Swarm state: membership, users + salted hashes, access rules. Durable. |

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
