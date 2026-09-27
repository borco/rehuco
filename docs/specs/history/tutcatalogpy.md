# TutCatalogPy

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

## Compared with rehuco

| Capability | TutCatalogPy | rehuco |
| --- | --- | --- |
| `info.tc` sidecar | Yes (YAML) | `.rehu` (JSON); reads and converts `.tc`, never writes it |
| SQLite cache of the catalog | Yes | Planned |
| Incremental scan | Basic | Planned |
| Catalog browser (sortable/filterable) | Yes | Planned |
| Separate viewer app | Yes | Single agent; viewing and editing are both built into it |
| App state persistence | `.ini` (QSettings) | `.rehuco` (per-machine) + app settings |
| Duration via ffprobe | Yes | Yes — stored field, can also measure itself from the media |
| Scraping | Yes | Yes — built-in scrapers (ArtStation, Udemy), browser-drop and URL-drop handling |

## Can rehuco work for its data?

**Yes.** The `info.tc` maps through the same [field-schema](../field-schema.md) `.tc`→`.rehu` adapter
(LocalEdit3). The SQLite cache needs **no import** — like rehuco's `.rehudb` it is declared rebuildable from
the sidecars, so only the `.tc` files carry unique data.
