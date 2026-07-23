# rehuco

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![QA](https://github.com/borco/rehuco/actions/workflows/qa.yml/badge.svg)](https://github.com/borco/rehuco/actions/workflows/qa.yml)
[![Coverage](https://img.shields.io/badge/Coverage-blue)](https://codecov.io/gh/borco/rehuco)
[![Windows](https://img.shields.io/codecov/c/github/borco/rehuco?flag=windows&label=Windows)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=windows)
[![macOS](https://img.shields.io/codecov/c/github/borco/rehuco?flag=macos&label=macOS)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=macos)
[![Linux](https://img.shields.io/codecov/c/github/borco/rehuco?flag=linux&label=Linux)](https://app.codecov.io/gh/borco/rehuco?flags%5B0%5D=linux)

rehuco is a distributed resource management system for tutorials and reference images.

See the [design specs](specs/README.md) for architecture and implementation details.

## Roadmap

The build is organized into milestones, each mapping to a personal use-case and adding one new
architectural spine. See the [implementation plan](specs/implementation-plan.md) for detail.

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

## rehuco packages

rehuco is published as three separate packages on PyPI.

| Package | Description | PyPI | Downloads | Python |
| --- | --- | --- | --- | --- |
| [rehuco-agent](https://pypi.org/project/rehuco-agent/) | PySide6 desktop GUI | [![PyPI](https://img.shields.io/pypi/v/rehuco-agent)](https://pypi.org/project/rehuco-agent/) | [![Downloads](https://static.pepy.tech/badge/rehuco-agent)](https://pepy.tech/project/rehuco-agent) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-agent)](https://pypi.org/project/rehuco-agent/) |
| [rehuco-core](https://pypi.org/project/rehuco-core/) | Shared library: models, `.rehu` I/O, sync primitives | [![PyPI](https://img.shields.io/pypi/v/rehuco-core)](https://pypi.org/project/rehuco-core/) | [![Downloads](https://static.pepy.tech/badge/rehuco-core)](https://pepy.tech/project/rehuco-core) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-core)](https://pypi.org/project/rehuco-core/) |
| [rehuco-node](https://pypi.org/project/rehuco-node/) | Headless REST node | [![PyPI](https://img.shields.io/pypi/v/rehuco-node)](https://pypi.org/project/rehuco-node/) | [![Downloads](https://static.pepy.tech/badge/rehuco-node)](https://pepy.tech/project/rehuco-node) | [![Python](https://img.shields.io/pypi/pyversions/rehuco-node)](https://pypi.org/project/rehuco-node/) |

## Generic libraries (temporarily hosted)

Two generic, reusable libraries under the author's `borco` namespace are **not rehuco-specific**. They are
developed in this monorepo for now and will later move to their own repository. If you install them from PyPI,
that move is handled automatically.

| Package | Description | PyPI | Downloads | Python |
| --- | --- | --- | --- | --- |
| [borco-core](https://pypi.org/project/borco-core/) | Generic reusable classes with no GUI dependency | [![PyPI](https://img.shields.io/pypi/v/borco-core)](https://pypi.org/project/borco-core/) | [![Downloads](https://static.pepy.tech/badge/borco-core)](https://pepy.tech/project/borco-core) | [![Python](https://img.shields.io/pypi/pyversions/borco-core)](https://pypi.org/project/borco-core/) |
| [borco-pyside](https://pypi.org/project/borco-pyside/) | Generic reusable PySide6/Qt classes (e.g. `ApplicationSingleton`) | [![PyPI](https://img.shields.io/pypi/v/borco-pyside)](https://pypi.org/project/borco-pyside/) | [![Downloads](https://static.pepy.tech/badge/borco-pyside)](https://pepy.tech/project/borco-pyside) | [![Python](https://img.shields.io/pypi/pyversions/borco-pyside)](https://pypi.org/project/borco-pyside/) |
