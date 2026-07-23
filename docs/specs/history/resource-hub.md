# Resource Hub

<https://gitlab.com/iborco-software/tutcatalog/resource-hub>

The direct predecessor to rehuco (2026, Python/PySide6, Qt6, Python 3.14) — "a librarian for your
tutorials, reference images and other learning resources." It broadened the framing from "tutorial
catalog" to a general resource librarian and settled much of the toolchain rehuco inherits: uv, a
`task` build flow, PyInstaller packaging with a post-commit build hook, and QtAds docking hosting a
QML `QQuickWidget`.

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

Scan resource folders, cache into SQLite, and present a docked (QtAds) desktop UI mixing QtWidgets
and a QML surface — the same "both QML and QtWidgets" approach rehuco carries forward. It is the
closest thing to rehuco's intended shape, which is why so much of it is *reference-and-adapt* rather
than *port*.

## Compared with rehuco

| Capability | Resource Hub | rehuco |
| --- | --- | --- |
| `.tc` reader (YAML) | Yes | reused as the design/read reference for the `.tc`→`.rehu` adapter (LocalEdit3) |
| SQLite cache + scan | Yes (QtSql) | `.rehudb` built by the node (CacheDB3) |
| Browsers (docked tables) | Yes | CacheDB4 |
| QtAds docking + QML surface | Yes | Adopted — QtAds document-dock shell landed with LocalEdit2.0; first QML dock still ahead ([QtAds appendix](../appendices/qt-ads.md)) |
| `ApplicationSingleton` / file-association helpers | via pyside-ibo | reimplemented in `borco-core`/`borco-pyside`; file-association proven by the pre-work spike |
| Standalone packaging | PyInstaller (+ post-commit build) | native installers deferred; **Briefcase** evaluated in pre-work; `uv tool install` meanwhile |
| Node / web / tablet | No | WatchTutorial |
| Borrow offline, multi-node sync | No | Borrowing / Swarm |

## Can rehuco work for its `.tc`?

**Yes**, and rehuco already builds on it: `tc_reader.py` is the concrete reference behind rehuco's
[field-schema](../field-schema.md) and the read-half of the LocalEdit3 migration. The YAML `.tc` maps through
the same `.tc`→`.rehu` adapter; the SQLite cache is rebuildable and carries no unique data. Resource
Hub is less "a catalog to migrate from" than "the running start rehuco was rebuilt from" — a fresh
git history, old repo kept read-only, its design absorbed rather than its code carried verbatim.
