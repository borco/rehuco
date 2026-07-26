# rehuco-node

[![PyPI](https://img.shields.io/pypi/v/rehuco-node)](https://pypi.org/project/rehuco-node/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/rehuco-node)](https://pypi.org/project/rehuco-node/)

*A reserved name for a future headless node in [rehuco](https://borco.github.io/rehuco/). Nothing is
implemented yet — installing this package gets you a version constant.*

[View on PyPI](https://pypi.org/project/rehuco-node/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Empty.** This package holds its name on PyPI and takes part in the release plumbing alongside the
others in the monorepo. It contains no service, no endpoints, and no client — one module with a
docstring and a `__version__`. There is nothing here to install for a reason.

Today, rehuco is a desktop editor for `.rehu` sidecar files
([rehuco-agent](https://pypi.org/project/rehuco-agent/)). It does not talk to anything over a network.

## What it is intended to be

A headless service that answers for the resources one machine owns, so that several machines can
eventually share a catalog. That means a REST API, discovery on the local network, and sync — none of
it written, none of it scheduled, and possibly none of it ever: whether it is needed at all is a
question the desktop editor has to answer first.

The [design specs](https://borco.github.io/rehuco/specs/nodes/) describe the intended shape in
detail. They are a design, not a description of released software.

## Installation

There is no reason to install this package yet. When there is, it will be documented here.

## License

[MIT](https://github.com/borco/rehuco/blob/master/LICENSE)
