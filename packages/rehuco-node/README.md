# rehuco-node

[![PyPI](https://img.shields.io/pypi/v/rehuco-node)](https://pypi.org/project/rehuco-node/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/rehuco-node)](https://pypi.org/project/rehuco-node/)

*Headless REST node for [rehuco](https://borco.github.io/rehuco/): serve and sync `.rehu` collections over a local network.*

[View on PyPI](https://pypi.org/project/rehuco-node/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Pre-alpha.** Not yet functional. See [GitHub Issues](https://github.com/borco/rehuco/issues) and the
[project board](https://github.com/users/borco/projects/5) for what's planned and in progress.

## What it is

`rehuco-node` is the headless server component of the [rehuco](https://borco.github.io/rehuco/) distributed
resource management system. It runs on always-on machines — a NAS, a home server, or a cloud VPS — and
exposes a REST API over the local network so that desktop agents can sync `.rehu` collections with it.

It is designed to run on low-spec hardware such as the QNAP TS-230 (glibc 2.23, aarch64), with no GUI
dependencies.

## Goals

`rehuco-node` aims to be:

- **MIT licensed** — usable in open-source or closed-source projects freely
- **Dependency-light** — FastAPI + uvicorn + zeroconf; no GUI stack
- **Low-spec compatible** — installable on NAS hardware via `uv tool install rehuco-node`
- **Self-announcing** — advertises itself on the local network via mDNS (zeroconf)
- **Typed** — fully annotated public API with a `py.typed` marker for type-checker integration

## Installation

```bash
pip install rehuco-node
```

Or on a NAS or server using [uv](https://docs.astral.sh/uv/):

```bash
uv tool install rehuco-node
```

## Versioning

`rehuco-node`, `rehuco-core`, and `rehuco-agent` share a single version number and are released together.

## License

[MIT](https://github.com/borco/rehuco/blob/master/LICENSE)
