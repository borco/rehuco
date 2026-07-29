# Changelog

All notable changes to `borco-pyside` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`borco-pyside` only, and its releases are tagged `borco-pyside-X.Y.Z`.

## [Unreleased]

## [0.0.2] - 2026-07-01

### Changed

- README now links to the PyPI project and the GitHub repository. No functional change — the released
  code is identical to `0.0.1`.

## [0.0.1] - 2026-07-01

Initial release, published to reserve the name on PyPI.

### Added

- `ApplicationSingleton` (`borco_pyside.core.application_singleton`) — a single-instance guard built on
  `QLocalServer`/`QLocalSocket`: the first process serves, later ones forward their argv to it and exit.
  Moved here out of the desktop app so it could be reused.
