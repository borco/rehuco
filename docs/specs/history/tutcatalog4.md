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
| `info.tc` view / edit | Yes | Yes — generic editor plus a typed field toolkit (text, switch, tag list, date, rating, duration, size, choice, path, image count, …) |
| Markdown description editor | Yes (Scintilla) | Yes — rendered viewer plus a Scintilla-based editor (line numbers, wrapping, dropped-selection HTML→Markdown) |
| Tutorial rich viewer (images) | Yes | Yes — screenshot lightbox (click-to-maximize, prev/next, hideable strip), path-based rename-from-suggestions |
| ReferenceImages type (`.cbz`, samples) | Yes | Yes, basic — type + fields + a read-only Content Images viewer over the archive; redaction/search/slideshow are still planned reference-image-richness work |
| Collections (folder-of-folders) | Yes (recursive scan) | `Collection` type exists (declared for its identity/badge alone) but its **field set is deferred** — a real collection carries no type-specific fields yet; grouping several files into one resource needs the multi-file manifest, **not yet specified**. Folder scanning/aggregation itself needs the still-unbuilt cache |
| Duration/size "Compute" | Yes (mediainfo) | Yes — duration, size and image-count fields each measure themselves on demand (bundled media library or configured `ffprobe` for duration) and show the result beside the stored value |
| Checksums | Yes (`.sfv`) | Yes — algorithm-tagged checksums as task-queue jobs, per-resource or a folder sweep |
| SQLite cache + browser | Yes | Planned |
| Per-site scrapers | Yes (6 sites) | Yes, 2 sites so far (ArtStation, Udemy) plus browser-drop/URL-drop handling and an image pipeline; the geckodriver+BeautifulSoup approach is explicitly the cautionary predecessor, with an LLM URL-extraction fallback still deferred |
| Windows `.tc` association | Yes (registry) | Yes — Windows ProgID/AUMID and macOS `QFileOpenEvent` double-click-to-open, single-instance forwarding |

## Can rehuco work for its `info.tc`?

**Yes — most directly of all.** rehuco's v1 schema is literally the tc4 `.tc` field set mapped to
`.rehu` (see the field-by-field table in [field-schema](../field-schema.md)): renames
(`tags`→`advertised_tags`, `extraTags`→`extra_tags`), scalar `title`/`publisher`/`url`→`sources`,
`duration` split into `original`/`current`/`advertised`, `level`→multi-choice, and the ReferenceImages
`duration` leak dropped in favor of a (scanned) `images_count`. The adapter reads YAML, rehuco writes
JSON. Two things stay open on rehuco's side, not tc4's: the **Collection** type's field set and the
**multi-file manifest** for grouped resources.
