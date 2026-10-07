# TutCatalogPy3 ✓

<https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy3>

A short third Python iteration (2022, ~6 months). Viewer-focused, with attention on packaging and
distribution — PyInstaller `.app` bundles, generated `.icns` icons, Linux `.desktop`/MIME wiring —
carrying `design/` and `demos/` explorations. Superseded quickly by the return to C++ in TutCatalog4.

## File formats

- **`info.tc`** — per-tutorial **YAML** sidecar, same field family (examples under
  `examples/tut1`, `examples/tut2`).
- **SQLite** — via SQLAlchemy (scan/cache lineage continues).
- **`.desktop` + `.tc` MIME** (`application/x-tc`) — Linux file-type registration, same recipe as
  TutCatalogPy2.
- **PyInstaller** `.spec` + `.icns` — standalone macOS bundling.

## What it did

Primarily a viewer for `info.tc`, plus real work on shipping it as a double-clickable, OS-registered
app. It never grew into a full catalog/editor before being set aside.

## Feature ledger

| Feature | TutCatalogPy3 | rehuco |
| --- | --- | --- |
| `info.tc` sidecar | YAML | Built — `.rehu` (JSON); `.tc` read and converted |
| Viewer | Yes | Built |
| File association, double-click open | Linux MIME | Built — Windows, macOS and Linux |
| Standalone packaging | PyInstaller `.app` | Built — Briefcase installers for Windows and macOS. Linux ships through `uv tool install` |
| Scraping | Yes | Built — ArtStation and Udemy, plus a user script |
| SQLite cache and browser | Basic | Built |

## Importing its data

The `info.tc` converts as in [TutCatalog](tutcatalog.md).
