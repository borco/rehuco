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
| `info.tc` sidecar | Yes (YAML) | `.rehu` (JSON); `.tc` adapter (LocalEdit3) |
| Viewer | Yes | LocalEdit1 / LocalEdit5 |
| `.tc` association + double-click open | Yes (Linux MIME) | LocalEdit1 + file-association pre-work spike |
| Standalone packaging | PyInstaller | native installers deferred; **Briefcase** evaluated in pre-work spike |
| Scraping | Yes (scrapper) | deferred (acquisition tooling) |
| SQLite cache / browser | Basic | `.rehudb` (CacheDB3) / browsers (CacheDB4) |

## Can rehuco work for its `info.tc`?

**Yes**, via the same [field-schema](../field-schema.md) `.tc`→`.rehu` adapter (LocalEdit3); the sidecar shape
is unchanged from the rest of the lineage. Its main contribution is packaging/OS-integration prior
art rather than data to migrate — the file-association mechanics rehuco de-risks in pre-work echo the
`.desktop`/MIME work here (rehuco adds macOS `QFileOpenEvent` and Windows ProgID/AUMID).
