# Tutcatalog 3 ✓

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

## Feature ledger

The same features as [TutCatalog](tutcatalog.md), only partly implemented.

| Feature | Tutcatalog 3 | rehuco |
| --- | --- | --- |
| `info.tc` sidecar | YAML | Built — `.rehu` (JSON); `.tc` read and converted |
| View / edit | Partial | Built |
| Catalog browser | Partial | Built — see [TutCatalog](tutcatalog.md) |
| Duration via ffprobe | Yes | Built |
| Scraping (cygwin, BeautifulSoup) | Yes | Built — ArtStation and Udemy, plus a user script |
| Per-machine config | `.tutcatalogrc` | Built — `.rehuco` and app settings |

## Importing its data

The `info.tc` is the same family as TutCatalog's; the same adapter applies.
