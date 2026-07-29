# Changelog

All notable changes to `borco-core` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`borco-core` only, and its releases are tagged `borco-core-X.Y.Z`.

## [Unreleased]

## [0.1.0] - 2026-07-29

The first version with anything in it: `0.0.1` and `0.0.2` held the name and shipped no code, so
everything below is new rather than changed.

### Added

- `atomic_write` — crash-safe file writes: write a temporary sibling, flush and `fsync`, then replace
  atomically.
- Windows platform integration — per-user (`HKCU`) registry helpers, file-type association, and both
  directory and file-extension shell context menus.
- Linux platform integration — XDG data-directory helpers with cache refresh, desktop entries, MIME
  packages, and icon-theme installation.

## [0.0.2] - 2026-07-01

### Changed

- README now links to the PyPI project and the GitHub repository. No functional change — the released
  code is identical to `0.0.1`.

## [0.0.1] - 2026-07-01

Initial release, published to reserve the name on PyPI rather than to be used. The distribution contains
a version constant and a `py.typed` marker and nothing else: there is no functionality to import yet.
