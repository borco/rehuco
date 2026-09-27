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
| `info.tc` sidecar | Yes (YAML) | `.rehu` (JSON); reads and converts `.tc`, never writes it |
| Display fields | Yes | Yes — generic and typed field toolkit |
| Edit fields | TODO (never landed) | Yes — atomic-saved edits through the typed field toolkit |
| SQLite cache + search | Yes | Planned |
| `.tc` file-type association | Yes (Linux MIME) | Yes — Windows ProgID/AUMID and macOS `QFileOpenEvent`, single-instance forwarding |
| Scraping | Yes (scrapper tool) | Yes — built-in scrapers (ArtStation, Udemy), browser-drop and URL-drop handling |
| Duration via ffprobe | Yes | Yes — stored field, can also measure itself from the media |

## Can rehuco work for its `info.tc`?

**Yes.** Its `examples/info.tc` is exactly the field set rehuco's [field-schema](../field-schema.md)
enumerates; the `.tc`→`.rehu` adapter (LocalEdit3) handles the renames (`tags`→`advertised_tags`,
`extraTags`→`extra_tags`) and the scalar `title`/`publisher`/`url`→`sources` fold. The SQLite cache
is rebuildable and needs no import.
