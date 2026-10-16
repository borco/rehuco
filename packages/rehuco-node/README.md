# rehuco-node

[![PyPI](https://img.shields.io/pypi/v/rehuco-node)](https://pypi.org/project/rehuco-node/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/rehuco-node)](https://pypi.org/project/rehuco-node/)

*The local node of [rehuco](https://borco.github.io/rehuco/): a process the desktop app runs beside itself, as the
same user, for as long as it runs.*

[View on PyPI](https://pypi.org/project/rehuco-node/) · [View on GitHub](https://github.com/borco/rehuco)

## What it does today

`rehuco-node [--settings-dir DIR]` runs until stopped. While it runs it writes a heartbeat file,
`node/node.json` (its pid, version, start time and last beat), every two seconds, and a log,
`node/rehuco-node.log`, both under the folder it shares with [rehuco-agent](https://pypi.org/project/rehuco-agent/)
(`%LOCALAPPDATA%\borco\rehuco` on Windows, `~/Library/Application Support/borco/rehuco` on macOS, the XDG data folder
on Linux). It stops on SIGINT or SIGTERM, and when its standard input reaches end of file: the agent starts it with a
pipe and holds that pipe, so an agent that quits, or crashes, takes the node down with it.

The agent starts the node a few seconds after its window is up and stops it when it quits. *Settings* > *System
Integration* has the switch and shows whether the node runs. `rehuco-agent --node` runs the same program, so the
packaged app needs no second executable.

## What it is meant to become

The place where the web pages for a tablet, the long jobs such as checksum runs, and the store for borrowed copies
live. The [design specs](https://borco.github.io/rehuco/specs/nodes/) describe that shape; they are a design, not a
description of released software.

## Installation

```sh
pip install rehuco-node
```

Installing rehuco-agent brings it along.

## License

[MIT](https://github.com/borco/rehuco/blob/master/LICENSE)
