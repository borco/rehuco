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

## Feature ledger

| Feature | TutCatalogPy2 | rehuco |
| --- | --- | --- |
| `info.tc` sidecar | YAML | Built — `.rehu` (JSON); `.tc` read and converted |
| Display fields | Yes | Built |
| Edit fields | Never landed | Built |
| Tags dock: authors and publishers with counts, and flags (complete, error, has `info.tc`, cover, checked, disk online); click cycles ignore / include / exclude | Yes (`tags_dock.py`) | **TBD** as a dock. Filtering: Built for typed tokens (`folder`, `authors`, `tags`, `publishers`, `type`) in the table browsers' filter line; click-to-filter only for authors (right-click an authors cell, #460). **Not built**: filtering by collection or learning path, include/exclude, saved filters. Filtering by flag is not built either |
| SQLite cache and search | Yes | Built — `.rehudb` and the filter line |
| `.tc` file-type association | Linux MIME | Built for `.rehu` on Windows, macOS and Linux (`application/x-rehuco`) |
| Scraping (scrapper tool) | Yes | Built — ArtStation and Udemy, plus a user script |
| Duration via ffprobe | Yes | Built |
| `learning_paths`, `rating`, `viewed`/`todo`/`keep`/`online` flags | Yes | Built as fields |

## Importing its data

`examples/info.tc` is the field set rehuco's [field schema](../field-schema.md) lists; the adapter applies the
renames (`tags` → `advertised_tags`, `extraTags` → `extra_tags`) and the `title`/`publisher`/`url` → `sources` fold.
The cache needs no import.
