# borco-core

[![PyPI](https://img.shields.io/pypi/v/borco-core)](https://pypi.org/project/borco-core/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/borco-core)](https://pypi.org/project/borco-core/)

*Generic, reusable Python classes with no GUI dependencies.*

[View on PyPI](https://pypi.org/project/borco-core/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Pre-alpha.** This package is **not rehuco-specific** — it is a home for generic, reusable code. It currently
lives inside the [rehuco](https://borco.github.io/rehuco/) monorepo for convenience, but is **scheduled to move
to its own repository** once its API settles. Do not depend on its location here.

## What it is

`borco-core` holds small, general-purpose building blocks that carry **no GUI (PySide/Qt) dependency**, so they
are usable on headless servers and low-spec hardware. Qt-dependent counterparts live in `borco-pyside`.

## Installation

```bash
pip install borco-core
```
