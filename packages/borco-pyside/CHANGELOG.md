# Changelog

All notable changes to `borco-pyside` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`borco-pyside` only, and its releases are tagged `borco-pyside-X.Y.Z`.

## [Unreleased]

## [0.1.0] - 2026-07-29

`ApplicationSingleton` was the whole package through `0.0.2`; everything below joined it since.

### Added

- Theming — a theme manager cycling follow-system/light/dark, a theme model and menu, an
  application-palette-change notifier, glyph-based action icons, and SVG recolouring.
- Dockable dialogs — `CDockWidget`-hosted dialog panels that can be restored on start, with their own
  frame, manager and settings.
- Widgets — elided label, flow layout, rating, rich-text view, message banner, unbounded spin box,
  wrapping check box, horizontal line, line-edit clear action, and layout/dynamic-property helpers.
- QtAds helpers — a focus tracker and widget wrappers.
- `borco_pyside.core` — property helpers and a connection list.
- Windows window activation.

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
