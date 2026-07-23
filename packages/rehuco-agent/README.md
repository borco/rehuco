# rehuco-agent

[![PyPI](https://img.shields.io/pypi/v/rehuco-agent)](https://pypi.org/project/rehuco-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/rehuco-agent)](https://pypi.org/project/rehuco-agent/)

*PySide6 desktop GUI for [rehuco](https://borco.github.io/rehuco/): open, view, and edit `.rehu` files.*

[View on PyPI](https://pypi.org/project/rehuco-agent/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Pre-alpha.** Not yet functional. See [GitHub Issues](https://github.com/borco/rehuco/issues) and the
[project board](https://github.com/users/borco/projects/5) for what's planned and in progress.

## What it is

`rehuco-agent` is the desktop GUI for the [rehuco](https://borco.github.io/rehuco/) distributed resource
management system. It runs on capable desktop machines (Linux, macOS, Windows) and provides:

- **Single-instance launcher** — double-click a `.rehu` file to open it in the running instance
- **Rich viewer** — common fields, Markdown, and an image strip per resource
- **Inline editing** — edit fields and save atomically back to disk
- **Swarm sync** — stays in sync with other nodes via `rehuco-core`'s sync engine

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

## Versioning

`rehuco-agent`, `rehuco-core`, and `rehuco-node` share a single version number and are released together.

## License

[MIT](https://github.com/borco/rehuco/blob/master/LICENSE)
