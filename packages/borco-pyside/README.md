# borco-pyside

[![PyPI](https://img.shields.io/pypi/v/borco-pyside)](https://pypi.org/project/borco-pyside/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/borco-pyside)](https://pypi.org/project/borco-pyside/)

*Generic, reusable PySide6/Qt classes and utilities.*

[View on PyPI](https://pypi.org/project/borco-pyside/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Pre-alpha.** This package is **not rehuco-specific** — it is a home for generic, reusable Qt code. It is currently
developed inside the [rehuco](https://borco.github.io/rehuco/) monorepo and will later move to its own repository.
If you use `borco-pyside` from PyPI, this move will be handled automatically.

## What it is

`borco-pyside` holds general-purpose building blocks that depend on **PySide6/Qt**. GUI-free counterparts live in
`borco-core`. It is the successor of an earlier standalone PySide utility library.

Currently provides:

- **`borco_pyside.core.ApplicationSingleton`** — a single-instance guard that forwards argv from later launches
  to the first process, built on `QLocalServer`/`QLocalSocket`.

## Installation

```bash
pip install borco-pyside
```
