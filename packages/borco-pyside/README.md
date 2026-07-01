# borco-pyside

[![PyPI](https://img.shields.io/pypi/v/borco-pyside)](https://pypi.org/project/borco-pyside/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/borco-pyside)](https://pypi.org/project/borco-pyside/)

*Generic, reusable PySide6/Qt classes and utilities.*

## Status

**Pre-alpha.** This package is **not rehuco-specific** — it is a home for generic, reusable Qt code. It currently
lives inside the [rehuco](https://borco.github.io/rehuco/) monorepo for convenience, but is **scheduled to move
to its own repository** once its API settles. Do not depend on its location here.

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
