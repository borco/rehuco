# TutCatalogPy2

<https://gitlab.com/iborco-software/tutcatalog/tutcatalogpy2>

The second Python iteration (2021–2022, Python/PySide2). Described in its own README as "the fourth
incarnation" of TutCatalog. Leans into the SQLite cache for fast access/search and adds proper OS
integration (Linux `.desktop` files + a `.tc` MIME type), but stayed read-only — editing `info.tc`
and the viewer app were both still TODO when it stopped.

## File formats

- **`info.tc`** — per-tutorial **YAML** sidecar (a full example ships in `examples/info.tc`): the
  familiar field set — publisher, title, author list, released, duration, level, url, the boolean
  flags (`complete`/`todo`/`viewed`/`keep`/`online`), tags/extraTags, `learning_paths`, `rating`, and
  a Markdown `description`.
- **SQLite cache** — scanned catalog index (SQLAlchemy; `catalog/config.py`). Rebuildable.
- **`.ini`** — `QSettings` app state.
- **MIME**: registers `application/x-tc` for `.tc` (Linux `user-extension-tc.xml`) so the file type
  is recognized by the desktop.

## What it did

Scan folders, parse and **display** `info.tc` in a cached, searchable catalog. Editing was not yet
implemented. Carried a dedicated **scrapper** tool for seeding metadata from publisher pages.

## Compared with rehuco

| Capability | TutCatalogPy2 | rehuco |
| --- | --- | --- |
| `info.tc` sidecar | Yes (YAML) | `.rehu` (JSON); `.tc` adapter (A3) |
| Display fields | Yes | A1 / A2 |
| Edit fields | TODO (never landed) | A1 atomic save; A2 typed toolkit |
| SQLite cache + search | Yes | `.rehudb` (B3), browsers (B4) |
| `.tc` file-type association | Yes (Linux MIME) | A1 + file-association pre-work spike (macOS `QFileOpenEvent`, Windows ProgID/AUMID) |
| Scraping | Yes (scrapper tool) | deferred past C |
| Duration via ffprobe | Yes | field A2; auto-measure **TBD** |

## Can rehuco work for its `info.tc`?

**Yes.** Its `examples/info.tc` is exactly the field set rehuco's [field-schema](../field-schema.md)
enumerates; the `.tc`→`.rehu` adapter (A3) handles the renames (`tags`→`advertised_tags`,
`extraTags`→`extra_tags`) and the scalar `title`/`publisher`/`url`→`sources` fold. The SQLite cache
is rebuildable and needs no import.
