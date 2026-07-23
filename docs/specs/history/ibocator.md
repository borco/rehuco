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

## Compared with rehuco

Different problem, so most rows are N/A rather than "planned later":

| Capability | ibocator | rehuco |
| --- | --- | --- |
| Domain | Offline disk/volume contents | Per-resource tutorials / reference images / assets |
| Data model | One monolithic XML catalog | One `.rehu` sidecar per resource + rebuildable `.rehudb` cache |
| Rich per-item metadata | No | Yes — typed field schema (LocalEdit2) |
| Search a cache when media is offline | Yes (its whole point) | Partial, differently framed — mounts may be offline ([mounts & storage](../mounts-and-storage.md)); the cache is rebuildable, not a hand-made index |
| Web scraping / metadata enrichment | No | Deferred (acquisition tooling) |
| Distribution / multi-node | No | The Swarm milestone |

## Can rehuco work for its data?

**No, and by design it shouldn't.** ibocator's XML catalog describes *volumes and their file trees*,
not individually-described learning resources; rehuco's sidecar-per-resource model targets a
different thing entirely. There is no meaningful import path and — per the standing decision — no
code or format to carry over. It is a curiosity in the lineage, not a predecessor to migrate.
