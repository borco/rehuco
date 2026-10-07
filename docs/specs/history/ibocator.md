# ibocator

<https://sourceforge.net/projects/ibocator/>

The earliest ancestor (2010, C++/Qt4), and the odd one out: not a tutorial catalog at all but a
disk/volume cataloger in the spirit of [CdCat](https://sourceforge.net/projects/cdcat/) — index the
contents of offline media (CDs/DVDs/external drives) so their file trees stay searchable when the
media isn't mounted. It began as an e-book locator ("book-locator" → "elocator" → "ibocator") before
pivoting to CdCat cloning. It predates the whole TutCatalog line in both domain and data model, and
**nothing is ported from it** — it is recorded here only as the origin of the cataloging itch.

## File formats

- **XML catalog** (`.xml`) — a single monolithic document describing catalogued volumes and their
  file trees. ibocator reads the CdCat XML format (`libs/storage` `cdcatreader`) and writes its own
  `*.xml` catalogs (`MainWindow::saveFile`, "Save Catalog"). There is **no per-resource sidecar** —
  one file holds the whole catalog.
- Built on Qt4, GLib **gio** (filesystem access), boost, and googletest/googlemock.

## What it did

Scan a mounted volume, record its directory tree into the catalog, then browse and search that tree
later without the media present. A pure offline-media index — no metadata editing, no web scraping,
no per-item rich fields.

## Feature ledger

A different problem (offline volumes, not described resources), so most rows are N/A.

| Feature | ibocator | rehuco |
| --- | --- | --- |
| Index a volume's file tree | Yes | Not planned — a scan records `.rehu` records, not every file |
| Browse and search a catalog with the media offline | Yes | Partly — a root that is offline keeps its cached rows (a scan leaves them alone); [#452](https://github.com/borco/rehuco/issues/452) adds cached roots read through the access seam. Only records are cached, not file trees |
| CdCat XML import | Yes | Not planned |
| Per-item metadata | None | n/a |

## Importing its data

None, by decision: a volume tree is not a described resource, and nothing is carried over.
