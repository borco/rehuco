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

## Compared with rehuco

| Capability | TutCatalog | rehuco |
| --- | --- | --- |
| `info.tc` sidecar per tutorial | Yes (YAML) | `.rehu` (JSON); reads `.tc` via adapter (A3 migration) |
| View / edit fields | Yes (infoviewer) | A1 (generic), A2 (typed toolkit) |
| Markdown description | Yes | A1 view |
| Catalog browser (folders → table) | Yes | B4 (browsers), over the `.rehudb` cache (B3) |
| Duration via ffprobe | Yes | duration is a stored field (A2); auto-measuring it from the media isn't tied to a milestone slice — **TBD** |
| SFV checksums | Yes (cfv) | A7 (algorithm-tagged) |
| Metadata scraping | Yes (external script) | deferred past D (acquisition tooling) |
| Per-machine config | `.tutcatalogrc` (YAML) | `.rehuco` |
| Web / tablet, borrow, multi-node | No | Milestones C / D / deferred-swarm |

## Can rehuco work for its `info.tc`?

**Yes — this is precisely what rehuco's schema targets.** rehuco's [field schema](../field-schema.md)
is explicitly "`.tc`-compatible," derived from the same field vocabulary (ground-truthed on tc4, its
lineal successor). A `.tc`→`.rehu` adapter reads the YAML into rehuco's model (view-only at first,
full migration in slice A3); rehuco writes JSON `.rehu`, never `.tc`. Field renames apply on import
(`tags`→`advertised_tags`, `extraTags`→`extra_tags`) and the scalar `title`/`publisher`/`url` fold
into a `sources` record — all handled by the adapter.
