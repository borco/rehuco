# TutCatalog

<https://gitlab.com/iborco-software/tutcatalog/tutcatalog>

The first tutorial catalog (2016–2020, C++/Qt5) and the origin of the `info.tc` sidecar that every
later version — and rehuco itself — descends from. Two apps: **tutcatalog** (the catalog browser over
a tree of tutorial folders) and **infoviewer** (view/edit a single `info.tc`). The longest-lived of
the C++ generation (~430 logged hours).

## File formats

- **`info.tc`** — per-tutorial-folder sidecar, **YAML**. The source of truth for a tutorial's
  metadata (publisher, title, author, released, duration, level, url, tags, description, the boolean
  flags, …). This is the direct ancestor of rehuco's `.rehu`.
- **`.tutcatalogrc`** — per-machine config, **YAML** (e.g. `AppData/Local/.tutcatalogrc`): tutorial
  folder roots, the video-extension list, and paths to helper tools (`ffprobe`, `cfv`, the scrap
  script). The ancestor of rehuco's `.rehuco`.
- External tools: **ffprobe** (video duration), **cfv** (`.sfv` checksums), an external scraper
  script for pulling metadata off publisher pages.

## What it did

Scan configured folders for tutorial subfolders, read each `info.tc`, and present a browsable/
searchable catalog; open one in infoviewer to read the rendered Markdown description and edit fields.
Duration measured with ffprobe, integrity via SFV checksums, metadata seeded by scraping.

## Feature ledger

Status is as of rehuco today. **Built** runs in the agent; **Planned** names the issue or spec; **Not planned** is a
decision; **TBD** is a gap not yet decided or filed.

| Feature | TutCatalog | rehuco |
| --- | --- | --- |
| `info.tc` sidecar per tutorial | YAML | Built — `.rehu` is JSON; `.tc` is read and converted (one file or a folder tree), never written |
| Tags / authors / publishers / learning paths browser: a tree dock, each entry with a count, click to search | Yes (`tagsview.cpp`, `tagmodel.cpp`) | **TBD** — the grouping-entity plugins ([[plugins#grouping-entities]]) are specified, none is built |
| Rename a tag or author everywhere, from that tree (a rename onto an existing name merges) | Yes — rewrites every affected `info.tc` | **TBD** |
| Token search: `publisher:`, `author:`, `tag:`, `xtag:`, `path:`, `name:` | Yes | Built for typed tokens (`folder`, `authors`, `tags`, `publishers`, `type`) in the table browsers' filter line; click-to-filter only for authors (right-click an authors cell, #460). **Not built**: filtering by collection or learning path, include/exclude, saved filters |
| Saved searches (favourites) | Yes | **TBD** |
| Catalog browser (folders → table) | Yes | Built — Browsers panel over the `.rehudb` cache, with a filter line. A change made outside the app shows after the next scan |
| infoviewer: view and edit fields | Yes | Built |
| Rendered Markdown description | Yes | Built, with an editor |
| Duration via ffprobe | Yes | Built — a field that measures itself; ffprobe or a bundled media library |
| `.sfv` checksums (cfv) | Yes | Built, as rehuco's own `.checksum` records; a legacy `.sfv` is read to seed them, never written |
| Metadata scraping | External script | Built — ArtStation and Udemy built in, a user script supported |
| Per-machine config: folder roots | `.tutcatalogrc` | Built — roots live in the `.rehuco` file |
| Per-machine config: video extensions, tool paths | `.tutcatalogrc` | Built as app settings (Videos page) |

## Importing its data

`info.tc` is the YAML that rehuco's [field schema](../field-schema.md) was derived from, so it converts. Renames on
import: `tags` → `advertised_tags`, `extraTags` → `extra_tags`; the scalar `title`/`publisher`/`url` fold into a
`sources` record.
