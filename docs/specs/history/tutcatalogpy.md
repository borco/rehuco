# TutCatalogPy ✓

<https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy>

The first Python rewrite (2020–2021, Python/PySide, Qt5) — the jump off C++ that the rest of the
lineage stayed on. Ships two apps, **catalog** and **viewer**, and introduces a real SQLite cache
of the scanned tutorials (~370 logged hours).

## File formats

- **`info.tc`** — same per-tutorial **YAML** sidecar, unchanged.
- **SQLite cache** — a scanned index of tutorial folders for fast browse/search (SQLAlchemy;
  `catalog/config.py`). Rebuildable from the `.tc` files — a cache, not a source of truth. This is
  the ancestor of rehuco's `.rehudb`.
- **`.ini`** — Qt `QSettings` app state (window/column `header_state`, etc.).

## What it did

Scan configured folders, cache each tutorial's `info.tc` into SQLite, and present a fast sortable/
filterable catalog with a separate viewer. First appearance of the "scan → cache → browse" split that
rehuco formalizes as `.rehu` + `.rehudb`.

## Feature ledger

| Feature | TutCatalogPy | rehuco |
| --- | --- | --- |
| `info.tc` sidecar | YAML | Built — `.rehu` (JSON); `.tc` read and converted |
| SQLite cache of the scan | SQLAlchemy | Built — `.rehudb`, one per `.rehuco` |
| Incremental scan | Basic | Built — only records whose modification time or size changed are re-read |
| Sortable, filterable catalog | Yes | Built — table browsers with a filter line |
| Separate viewer app | Yes | Not planned — one app views and edits |
| Window and column state | `.ini` | Built — the layouts and the session are JSON files, the `.ini` keeps preferences ([#404](https://github.com/borco/rehuco/issues/404)) |
| Duration via ffprobe | Yes | Built |
| Scraping | Yes | Built — ArtStation and Udemy, plus a user script |

## Importing its data

The `info.tc` converts as in [TutCatalog](tutcatalog.md). The SQLite cache holds nothing the sidecars do not, so
nothing is imported from it.
