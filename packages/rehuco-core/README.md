# rehuco-core

[![PyPI](https://img.shields.io/pypi/v/rehuco-core)](https://pypi.org/project/rehuco-core/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/rehuco-core)](https://pypi.org/project/rehuco-core/)

*Shared library for [rehuco](https://borco.github.io/rehuco/): data models, `.rehu` file I/O, and sync primitives.*

[View on PyPI](https://pypi.org/project/rehuco-core/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Pre-alpha.** Not yet functional. See [GitHub Issues](https://github.com/borco/rehuco/issues) for what's
planned and in progress.

## What it is

`rehuco-core` is the foundation shared by the desktop agent (`rehuco-agent`) and the headless node
(`rehuco-node`) in the [rehuco](https://borco.github.io/rehuco/) distributed resource management system.

It provides:

- **Data models** — the `.rehu` file format for tutorials and reference images
- **File I/O** — atomic read and write of `.rehu` files
- **Sync primitives** — version vectors, activity log, conflict resolution, and tombstones

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
