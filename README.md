# rehuco

A personal, distributed catalog for tutorials, references, and creative assets.

The name is the stem of the file formats it owns: `.rehu`, `.rehuco`, `.rehudb`, `.rehusw`.

## What it is

rehuco manages a large, heterogeneous personal media collection spread across multiple machines —
local video tutorials, online course registrations, zip archives of reference images, Daz3D plugins,
3D objects, and more. It replaces a YAML sidecar file (`info.tc`) per tutorial folder with
`info.rehu` (JSON), adds a distributed node model, and supports offline use, multi-user access
control, and a web interface for tablet access.

Key design properties:

- **Self-describing data.** `.rehu` files live next to the content they describe. The SQLite cache
  (`.rehudb`) is rebuildable from `.rehu` files; it is a cache, never the source of truth.
- **No single always-on machine.** The system is a swarm of peer nodes, each capable of answering
  for itself, each tolerant of any other node being unreachable.
- **Offline-first.** Borrowing a resource onto a laptop and watching it without any network
  connection is a first-class use case.

## Monorepo layout

```text
rehuco/
├── packages/
│   ├── rehuco-core/          # shared models, .rehu I/O, field types, sync primitives
│   └── rehuco-node/          # headless REST service; runs on QNAP and other headless boxes
├── apps/
│   └── rehuco-agent/         # PySide6 desktop GUI — tray, viewer/editor, catalog/admin UI
└── docs/
    └── specs/
        ├── architecture-design.md
        └── implementation-plan.md
```

`rehuco-core` is a shared library.
`rehuco-node` is the headless service (FastAPI + uvicorn); it has a low `requires-python` floor
to remain installable on the QNAP TS-230.
`rehuco-agent` is the PySide6 desktop GUI; it is a node client for swarm operations.

## File formats

| Extension | Purpose |
| --- | --- |
| `.rehu` | Per-resource sidecar (JSON). Source of truth. |
| `.rehuco` | Per-machine config: folder roots, mounts, ownership flags, plugin list. |
| `.rehudb` | SQLite catalog cache. Derived; rebuildable. |
| `.rehusw` | Swarm state: membership, users + salted hashes, access rules. Durable. |

## History

| Project | Host | First Commit | Last Commit | Duration | Language | Qt |
| --- | --- | --- | --- | --- | --- | --- |
| [ibocator](https://sourceforge.net/projects/ibocator/) | SourceForge | 2010/01/26 | 2010/07/19 | 3 months | C++ | Qt4 |
| [tutcatalog](https://gitlab.com/iborco-software/tutcatalog/tutcatalog) | GitLab | 2016/08/09 | 2020/09/30 | 4 years | C++ | Qt5 |
| [tutcatalog (v3)](https://gitlab.com/iborco-software/tutcatalog/tutcatalog3) | GitLab | 2017/05/02 | 2017/05/29 | 1 month | C++/Python | Qt5 |
| [tutcatalogpy](https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy) | GitLab | 2020/08/19 | 2021/01/28 | 6 months | Python | Qt5 |
| [TutCatalogPy2](https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy2) | GitLab | 2021/06/01 | 2022/01/04 | 7 months | Python | Qt5 |
| [tutcatalogpy3](https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy3) | GitLab | 2022/02/07 | 2022/07/28 | 6 months | Python | Qt6 |
| [tutcatalog4](https://gitlab.com/iborco-software/tutcatalog/tutcatalog4) | GitLab | 2022/09/19 | 2024/12/22 | 2 years 3 months | C++/Python | Qt6 |
| [tutcatalog5](https://gitlab.com/iborco-software/tutcatalog/tutcatalog5) | GitLab | 2024/12/22 | 2025/04/15 | 4 months | Python | Qt6 |
| [resource-hub](https://gitlab.com/iborco-software/tutcatalog/resource-hub) | GitLab | 2026/04/27 | 2026/06 | 2 months | Python | Qt6 |
| **rehuco** | GitHub | 2026/06 | present | | Python | Qt6 |

GitHub mirrors:
[tutcatalog (v3)](https://github.com/borco/tutcatalog) ·
[TutCatalogPy2](https://github.com/borco/TutCatalogPy2)

## License

[MIT](LICENSE)
