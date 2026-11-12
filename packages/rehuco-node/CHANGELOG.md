# Changelog

All notable changes to `rehuco-node` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`rehuco-node` only, and its releases are tagged `rehuco-node-X.Y.Z`.

## [Unreleased]

## [0.4.0] - 2026-11-12

The first release with code: the 0.0.x versions on PyPI only held the name.

### Added

- **The local node**, the process the agent runs beside itself, keeping a heartbeat file and a log (#506).
- `rehuco-node [--settings-dir DIR]` writes `node/node.json` and `node/rehuco-node.log` under the agent's folder,
  and stops on SIGINT/SIGTERM or when its stdin closes, so it goes with the agent that started it (#506).

## [0.0.1] - 2026-06-30

Second name-reservation stub on PyPI, published a day after `0.0.0` and still carrying no service code.

## [0.0.0] - 2026-06-29

Name-reservation stub, published to PyPI so the name could not be taken by anyone else. Neither this
release nor `0.0.1` was built from this repository — when both were uploaded the repository contained no
Python packages at all, so there is no source in the history that corresponds to them.
