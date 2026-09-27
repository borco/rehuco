# TutCatalogPy3

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

## Compared with rehuco

| Capability | TutCatalogPy3 | rehuco |
| --- | --- | --- |
| `info.tc` sidecar | Yes (YAML) | `.rehu` (JSON); reads and converts `.tc`, never writes it |
| Viewer | Yes | Yes — read-only panels plus a screenshot lightbox |
| `.tc` association + double-click open | Yes (Linux MIME) | Yes — Windows ProgID/AUMID and macOS `QFileOpenEvent`, single-instance forwarding |
| Standalone packaging | PyInstaller | Yes — Briefcase-built installers (Windows/macOS) with declarative file association/icon/AUMID |
| Scraping | Yes (scrapper) | Yes — built-in scrapers (ArtStation, Udemy), browser-drop and URL-drop handling |
| SQLite cache / browser | Basic | Planned |

## Can rehuco work for its `info.tc`?

**Yes**, via the same [field-schema](../field-schema.md) `.tc`→`.rehu` adapter (LocalEdit3); the sidecar shape
is unchanged from the rest of the lineage. Its main contribution is packaging/OS-integration prior
art rather than data to migrate — the file-association mechanics rehuco de-risks in pre-work echo the
`.desktop`/MIME work here (rehuco adds macOS `QFileOpenEvent` and Windows ProgID/AUMID).
