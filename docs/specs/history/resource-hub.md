# Resource Hub ✓

<https://gitlab.com/iborco-software/tutcatalog/resource-hub>

The direct predecessor to rehuco (2026, Python/PySide6, Qt6, Python 3.14) — "a librarian for your tutorials,
reference images and other learning resources". A general resource librarian rather than a tutorial catalog; uv, a
`task` build flow, PyInstaller packaging, and QtAds docking hosting a QML `QQuickWidget`.

## File formats

- **`.tc`** — per-resource sidecar, **YAML** (read via `tc_reader.py`; the reader that answered
  rehuco's "decide the field lists" and the read-half of `.tc` migration). Same field family as the
  TutCatalog line.
- **SQLite cache** — scanned catalog via Qt's **QtSql** (QSql*), rebuildable from the sidecars.
- **Config / app state** — settings persisted per machine.
- Uses **[pyside-ibo](pyside-ibo.md)** as a submodule — the **second** snapshot (`ApplicationSingleton`,
  `SimpleProperty`/`ObjectProperty`, Windows registry / file-association helpers, logging stack) — the
  utilities rehuco reimplements natively in `borco-core`/`borco-pyside`.
- Ships as a **PyInstaller** standalone `.exe` used as the double-click opener for the resource files.

## What it did

Scanned resource folders, cached them into SQLite, and presented a docked (QtAds) desktop UI mixing QtWidgets and a
QML surface.

## Feature ledger

| Feature | Resource Hub | rehuco |
| --- | --- | --- |
| `.tc` reader (YAML) | Yes | Built — `.tc` → `.rehu` conversion, one file or a folder tree; never writes `.tc` |
| SQLite cache and scan | QtSql | Built — `.rehudb` |
| Browsers (docked tables) | Yes | Built — Browsers panel |
| QtAds docking | Yes | Built |
| Standalone packaging | PyInstaller `.exe` | Built — Briefcase installers for Windows and macOS |

## Importing its data

`tc_reader.py` was the reference behind rehuco's [field schema](../field-schema.md) and the `.tc` conversion. The
SQLite cache holds nothing the sidecars do not.
