# borco-pyside

[![PyPI](https://img.shields.io/pypi/v/borco-pyside)](https://pypi.org/project/borco-pyside/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/borco/rehuco/blob/master/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/borco-pyside)](https://pypi.org/project/borco-pyside/)

*Generic, reusable PySide6/Qt classes and utilities.*

[View on PyPI](https://pypi.org/project/borco-pyside/) · [View on GitHub](https://github.com/borco/rehuco)

## Status

**Pre-alpha.** This package is **not rehuco-specific** — it is a home for generic, reusable Qt code. It is currently
developed inside the [rehuco](https://borco.github.io/rehuco/) monorepo and will later move to its own repository.
If you use `borco-pyside` from PyPI, this move will be handled automatically.

## What it is

`borco-pyside` holds general-purpose building blocks that depend on **PySide6/Qt**. GUI-free counterparts live in
`borco-core`. It is the successor of an earlier standalone PySide utility library.

Currently provides:

- **`borco_pyside.core`** — application-lifecycle primitives: `ApplicationSingleton` (single-instance guard
  forwarding argv to the first process), `ConnectionList`, `SimpleProperty`/`TypedProperty`.
- **`borco_pyside.dialogs`** — a modeless, dockable dialog framework: `DockableDialog`,
  `DockableDialogFrame`, `DockableDialogManager`.
- **`borco_pyside.logging`** — logging for a GUI app: `LogBridge`, `LogModel`, `LogWidget`, `LogView`, plus
  console setup via `setup_console_logging`.
- **`borco_pyside.platforms`** — platform-specific modules, each imported only on its own platform (e.g.
  `platforms.windows.window_activation`).
- **`borco_pyside.qtads`** — generic helpers for `pyside6-qtads` (QtAds): `QtAdsFocusTracker`,
  `tab_close_button`, `tab_label`.
- **`borco_pyside.theming`** — theme switching, SVG recoloring, and themed action icons: `ThemeManager`,
  `ThemeMenu`, `ThemeModel`, `ActionIconThemeHandler`.
- **`borco_pyside.widgets`** — reusable widgets: `ItemListEditor`, `MessageBanner`, `Rating`,
  `RichTextView`, `StringListEditor`, `UnboundedSpinBox`, and other small building blocks.

## Installation

```bash
pip install borco-pyside
```
