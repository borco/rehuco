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

The near-term build follows four milestones, each mapping to a personal use-case and adding exactly
one new architectural spine. See the
[implementation plan](specs/implementation-plan.md) for detail.

- **A — Local view/edit** *(current)* — open, view, and edit a local `.rehu` for tutorials and
  reference images. One machine, no network, no login — a standalone, genuinely useful tool.
- **B — Cached database** — scan folders, cache the scan into `.rehudb`, browse and search the
  catalog on the desktop. Brings the app close to the original tutcatalog. Still local, no node.
- **C — WatchingTutorials** — a single headless node serves the catalog to a browser on the LAN;
  watch a tutorial from an iPad, progress remembered. Introduces the node and the web stack.
- **D — Borrowing** — borrow a copy onto a laptop, watch it with no network, reconcile progress
  and notes on return. Introduces two-party sync.

The full multi-node swarm, acquisition tooling, and richer plugins are deliberately deferred past
these four.

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
