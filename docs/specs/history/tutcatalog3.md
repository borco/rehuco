# Tutcatalog 3

<https://gitlab.com/iborco-software/tutcatalog/tutcatalog3>

A short-lived C++/Qt5 reimplementation of the original TutCatalog (2017, ~1 month). Its own README
calls it "a reimplementation of an older personal project. Some parts are still missing!" — a rewrite
that never reached parity, kept in the lineage as the first restart attempt.

## File formats

- **`info.tc`** — same per-tutorial **YAML** sidecar as TutCatalog, unchanged in shape.
- **`.tutcatalogrc`** — same per-machine **YAML** config (video extensions, tutorial folders,
  ffprobe path, scrap script).
- Tooling: **ffprobe** for duration; scraping moved to a **cygwin** Python stack
  (BeautifulSoup + python-dateutil).

## What it did

Same intent as TutCatalog — scan folders, read `info.tc`, browse/edit — re-architected in C++ with a
CMake/Conan build. It stalled early, so much of the browser/editor never landed; the design and the
`info.tc` format simply carried straight over to the Python rewrites that followed.

## Compared with rehuco

Feature-wise identical to [TutCatalog](tutcatalog.md) (same formats, same tools), so the rehuco
mapping is the same:

| Capability | Tutcatalog 3 | rehuco |
| --- | --- | --- |
| `info.tc` sidecar | Yes (YAML) | `.rehu` (JSON); `.tc` adapter (A3) |
| View / edit | Partial (incomplete rewrite) | A1 / A2 |
| Catalog browser | Partial | B4 over `.rehudb` (B3) |
| Duration via ffprobe | Yes | field A2; auto-measure **TBD** |
| Scraping (cygwin/BeautifulSoup) | Yes | deferred past C (acquisition tooling) |
| Per-machine config | `.tutcatalogrc` (YAML) | `.rehuco` |

## Can rehuco work for its `info.tc`?

**Yes** — the `info.tc` is byte-for-byte the same family as TutCatalog's, so the same
[field-schema](../field-schema.md) `.tc`→`.rehu` adapter (A3) applies with no extra work.
