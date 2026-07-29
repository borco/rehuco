# Changelog

All notable changes to `rehuco-agent` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`rehuco-agent` only, and its releases are tagged `rehuco-agent-X.Y.Z`. The section for the version being
released becomes the body of the GitHub Release, so each entry is written to be read there on its own.

## [Unreleased]

The first release built from this repository, and the first to ship a working application rather than a
stub — published to exercise the release plumbing end to end rather than because the app is ready to be
depended on. It starts a new minor series because `0.0.0` and `0.0.1` were spent on PyPI name-reservation
stubs that contained no application.

### Added

- Edits a resource's details from a `.rehu` file: title, authors, publisher, release date, URL, durations,
  sizes, rating, level, tags, flags, and a Markdown description.
- Shows a resource's screenshots in a strip beside the fields, with arrow-key and wheel navigation, and
  control over which images the strip shows.
- Converts legacy `.tc` catalogs to `.rehu`, keeping backups it can roll back if a conversion goes wrong.
- Leaves unrecognized fields untouched across a save, and opens a file written by a newer format version
  read-only rather than rewriting it.
- Saves atomically, and remembers each file's panel layout between sessions.
- Registers as the `.rehu` handler on Windows and Linux, from the app or via `--register`/`--unregister`;
  `--version` and `--info` report the version and the current registration.
- Ships installers for Windows (`.msi`), macOS (`.dmg`) and Linux (`.AppImage`).

### Known limitations

- The installers are neither code-signed nor notarized, so Windows SmartScreen and macOS Gatekeeper warn on
  first run and have to be overridden by hand.
- On Windows the packaged executable is a GUI-subsystem binary and prints nothing to a console, so
  `--version` and `--info` report through their exit code there; a source checkout prints normally.

## [0.0.1] - 2026-06-30

Second name-reservation stub on PyPI, published a day after `0.0.0` and still carrying no application.

## [0.0.0] - 2026-06-29

Name-reservation stub, published to PyPI so the name could not be taken by anyone else. Neither this
release nor `0.0.1` was built from this repository — when both were uploaded the repository contained no
Python packages at all, so there is no source in the history that corresponds to them.
