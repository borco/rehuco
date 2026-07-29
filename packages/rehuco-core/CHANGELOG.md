# Changelog

All notable changes to `rehuco-core` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`rehuco-core` only, and its releases are tagged `rehuco-core-X.Y.Z`.

## [Unreleased]

The first version carrying the library itself: `0.0.0` and `0.0.1` were name-reservation stubs built
outside this repository, so everything below is new rather than changed.

### Added

- `.rehu` documents — a model whose JSON read/write preserves unknown fields across a round-trip, plus
  the format definition, serialization, screenshots, and rename support.
- Lock derivation — why a parsed document is read-only, and the field-value coercion that goes with it.
- A migration runner and the migration chains for tutorials, reference images, and the `.rehu` core
  block, with the steps shared between them factored out.
- A plugin registry — the plugins a build ships, and an immutable index over them.
- Legacy `.tc` support — document and screenshot reading, description handling, and conversion to
  `.rehu`.
- Collection and learning-path entries, a titled index, and the shared constants.

## [0.0.1] - 2026-06-30

Second name-reservation stub on PyPI, published a day after `0.0.0` and still carrying no library code.

## [0.0.0] - 2026-06-29

Name-reservation stub, published to PyPI so the name could not be taken by anyone else. Neither this
release nor `0.0.1` was built from this repository — when both were uploaded the repository contained no
Python packages at all, so there is no source in the history that corresponds to them.
