# TutCatalog4

<https://gitlab.com/iborco-software/tutcatalog/tutcatalog4>

The one that actually got used (2022–2024, C++/Python, Qt6) — the only predecessor genuinely relied
on to view and edit `.tc` files day to day, and therefore rehuco's **ground truth**: its `Tutorial`
data model and `Viewer.qml` are the reference the [field schema](../field-schema.md) is derived from,
not the later drafts. A C++ core (yaml-cpp, Scintilla editor, plog) bridged to Python (pybind11) for
the scraper stack.

## File formats

- **`info.tc`** — per-folder **YAML** sidecar (parsed with yaml-cpp). A `type` field selects one of
  three resource kinds:
  - **Tutorial** — a tutorial folder.
  - **ReferenceImages** — a folder holding a `.cbz` (a zip of images renamed `.cbz`); scraping also
    writes original-size `sample-XX.jpg` files (`cover.jpg`, `image-01.jpg`, …).
  - **Collections** — a folder *of* folders; the catalog recurses, treating each subfolder as its own
    tutorial / reference-images / nested collection.
- **SQLite catalog** — C++-side scanned cache for browse/search. Rebuildable.
- **Config** — mixed TOML/YAML/JSON/INI settings in the tree.
- **`.sfv`** checksums; **mediainfo** for video duration.
- Python **scrapers**: artstation, class101, newmastersacademy, schoolism, udemy, wingfox.

## What it did

A working viewer/editor: scan folders (including recursive Collections), read/write `info.tc`, edit
the Markdown description in an embedded Scintilla editor, compute duration/size on demand ("Compute"
buttons), verify checksums, and seed metadata via per-site scrapers. It also handled the ReferenceImages
`.cbz` case and produced sample images.

## Feature ledger

| Feature | TutCatalog4 | rehuco |
| --- | --- | --- |
| `info.tc` view / edit | Yes | Built — `.rehu`; `.tc` read and converted |
| Markdown description editor | Scintilla | Built — Scintilla, with a rendered viewer |
| Tutorial viewer with images | Yes | Built — screenshot strip and lightbox |
| ReferenceImages type, `.cbz` | Yes | Built — the type, its fields, and a read-only Content Images view over archives and loose images |
| ReferenceImages: `sample-XX.jpg` files from scraping | Yes | Built — scraped images are saved beside the record as numbered screenshots |
| Collections (folder of folders, recursive scan) | Yes | **Partly** — the `collection` type exists, with no type-specific fields yet. Grouping several files into one resource needs the multi-file manifest, which is not specified ([[data-model#resource-scoping]]) |
| Duration / size "Compute" | mediainfo | Built — fields measure themselves beside the stored value; ffprobe or a bundled media library |
| `.sfv` checksums | Yes | Built, as `.checksum` records; a legacy `.sfv` is read to seed them |
| SQLite catalog and browser | Yes | Built — `.rehudb`, table browsers, a Roots column view, a preview |
| Scrapers: artstation, udemy | Yes | Built |
| Scrapers: class101, newmastersacademy, schoolism, wingfox | Yes | **TBD** |
| Windows `.tc` association | Registry | Built — Windows, macOS and Linux |
| Mixed TOML/YAML/JSON/INI config | Yes | Built as `.ini` today; moving to JSON ([#404](https://github.com/borco/rehuco/issues/404)) |

## Importing its data

`info.tc` is the ground truth for rehuco's schema ([field-schema](../field-schema.md)): renames
(`tags` → `advertised_tags`, `extraTags` → `extra_tags`), the `title`/`publisher`/`url` → `sources` fold, `duration`
split into `original`/`current`/`advertised`, `level` as a multi-choice, and ReferenceImages' `duration` dropped for a
scanned `images_count`. Open on rehuco's side: the Collection field set and the multi-file manifest.
