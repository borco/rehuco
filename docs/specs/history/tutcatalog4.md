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

## Compared with rehuco

| Capability | TutCatalog4 | rehuco |
| --- | --- | --- |
| `info.tc` view / edit | Yes | A1 (generic), A2 (typed toolkit) |
| Markdown description editor | Yes (Scintilla) | A1 view; editor via pyside6-scintilla (planned) |
| Tutorial rich viewer (images) | Yes | A5 (lightbox, folder-rename suggestions) |
| ReferenceImages type (`.cbz`, samples) | Yes | A6 (basic type + fields + viewer); redaction/search/slideshow deferred past C |
| Collections (folder-of-folders) | Yes (recursive scan) | `Collection` type is acknowledged but its **field set is deferred**; grouping several files into one resource needs the multi-file manifest, **not yet specified — TBD**. Folder scanning itself is B3 |
| Duration/size "Compute" | Yes (mediainfo) | fields modeled (A2); measured-by-scan is in the data model but no slice schedules the media-probe step — **TBD** |
| Checksums | Yes (`.sfv`) | A7 (algorithm-tagged) |
| SQLite cache + browser | Yes | `.rehudb` (B3), browsers (B4) |
| Per-site scrapers | Yes (6 sites) | deferred past C; the geckodriver+BeautifulSoup approach is explicitly the cautionary predecessor, with an LLM URL-extraction successor |
| Windows `.tc` association | Yes (registry) | A1 + file-association pre-work spike (ProgID/AUMID) |

## Can rehuco work for its `info.tc`?

**Yes — most directly of all.** rehuco's v1 schema is literally the tc4 `.tc` field set mapped to
`.rehu` (see the field-by-field table in [field-schema](../field-schema.md)): renames
(`tags`→`advertised_tags`, `extraTags`→`extra_tags`), scalar `title`/`publisher`/`url`→`sources`,
`duration` split into `original`/`current`/`advertised`, `level`→multi-choice, and the ReferenceImages
`duration` leak dropped in favor of a (scanned) `images_count`. The adapter reads YAML, rehuco writes
JSON. Two things stay open on rehuco's side, not tc4's: the **Collection** type's field set and the
**multi-file manifest** for grouped resources.
