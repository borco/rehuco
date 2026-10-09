# How rehuco Works

[[[how-it-works]]]

**Read this first, and read nothing else.** Everything here is true of the code today, and this page is
meant to be finished rather than followed: no link below is load-bearing, and where the design intends
more than exists, it says so. The other documents in `docs/specs/` describe intended design at length —
useful once you want depth on one topic, misleading as an answer to "what is this".

## The one idea

A **resource** is something you collected to learn from or work with: a video tutorial, an online
course, an archive of reference images. rehuco does not store your resources and does not move them. It
stores **what you know about them**, in a small JSON file that lives in the same folder as the resource
itself:

```text
Sculpting Series/          ← the resource, wherever you keep it
├── info.rehu              ← what rehuco knows about it
├── info01.jpg             ← screenshots, recognized by name
├── info02.png
└── ... the actual videos, archives, whatever it is
```

That file is the **source of truth**, and it travels with the content. Copy the folder to a USB stick
and the catalog entry goes with it. Nothing needs to be imported, registered, or indexed before a
resource can be read — the folder is enough. Every design choice below follows from wanting to keep that
true.

A resource can also be a single file rather than a folder (`foo.rehu` beside `foo01.jpg`); the file's
stem replaces `info` and nothing else changes.

## What a `.rehu` contains

Two reserved top-level keys, and everything else is a **block**:

```json
{
  "format_version": 2,
  "core": {
    "id": "6f1d2b3a-8c4e-4a2f-9b1d-3e7f5a6c8d90",
    "type": "tutorial",
    "created": "2026-07-20T00:00:00Z",
    "updated": "2026-07-20T00:00:00Z",
    "sources": [{ "title": "Sculpting Series", "publisher": "Example", "primary": true }],
    "authors": ["First Author", { "name": "Second", "url": "https://example.com/second" }],
    "description": "Markdown, rendered in the viewer."
  },
  "tutorial": {
    "format_version": 1,
    "rating": 4,
    "complete": true
  }
}
```

- **`format_version`** — the file's own layout version. Nothing else in the file is a version stamp,
  and no migration ever reshapes this key: it is the odometer, not the cargo.
- **`core`** — the fields every resource has, whatever kind it is: identity, timestamps, where it came
  from, authors, tags, a Markdown description.
- **`type`** — names the **active block**. Here `"tutorial"`, so the `tutorial` block holds this
  resource's type-specific fields (rating, completion, durations). Change the type and a different
  block becomes active; the outgoing one stays in the file.
- **Any other top-level key** is another block. A file can carry several — a `tutorial` block *and* a
  `reference_images` block, or a block belonging to a plugin this machine doesn't have installed.

**Resource types are plugins.** A plugin declares an ordered list of keys: the first is its real name,
the rest are old spellings accepted on read and rewritten on save. Three are built in — `tutorial`,
`reference_images`, `collection` — each declaring a badge color for its type chip. A `type` naming a
plugin that isn't installed still opens: the common fields render normally and the unknown block is
shown as-is, because a missing plugin must never cost you access to a file.

## The rules that explain the rest

Four invariants do most of the explaining, and each one exists to keep the file trustworthy:

1. **What isn't understood is preserved.** An unrecognized field, or a whole block belonging to a plugin
   this build has never heard of, comes back out of a save with its value unchanged. (The file is
   re-serialized in a canonical shape, so formatting is normalized — the data never is.) Another tool's
   data is not this tool's to discard.
2. **A file from the future is read, never rewritten.** If `format_version` — or the active block's own
   version — is newer than this build understands, the document opens **read-only** with the reason
   stated, rather than being saved back in a shape that loses whatever the newer version added. Six
   reasons can lock a document this way: a newer file, a newer active block, a field that is present
   but unreadable, a file that won't parse, a file that has gone missing, and a legacy `.tc` awaiting
   conversion. Each names its own remedy.
3. **Older files are upgraded by being saved.** A **migration chain** runs on load — one chain for the
   file layout, one per plugin for its own block. Each step is a `(version, upgrade)` pair, and the
   current version *is* the head of the chain rather than a number declared beside it, so the two cannot
   disagree. The v1→v2 step is the concrete example: v1 kept the common fields at the top level, v2
   moved them into the `core` block. A v1 file still opens, and saving it writes v2.
4. **Writes are atomic.** A save is written elsewhere and moved into place, so an interrupted write
   leaves the previous file intact rather than a half-written one. There is no undo for a lost file, so
   there is no version of this that is merely careful.

## What the app is made of

One program is runnable: **rehuco-agent**, a PySide6 desktop app. Open a `.rehu` — by double-clicking it
or from the app — and it appears as a set of dockable panels you can rearrange, tear off, and stack:

| Panel | What it shows |
| --- | --- |
| **Main View** | The resource's fields, read-only, under its location. Shown when a resource opens, alongside the description view; the editors below start hidden behind their toolbar buttons. The type badge leads the document toolbar, not this panel. |
| **Description View** | The rest of the resource read-only: its screenshots as a thumbnail strip, over the rendered Markdown description. Double-clicking a thumbnail fills the window with it; arrow keys or the wheel move through the set. |
| **Main Editor** | The same fields, editable, plus the type selector that decides which block is active. Its path row offers names built from the record — title, publisher, authors, year — and picking one renames the resource on disk: the folder for a directory-scoped resource, and for a standalone one every file named after it, archives and screenshots alike. |
| **Description** | The Markdown description in its own panel, so prose can be written with room. |
| **Images** | Which screenshots the strip shows: every sibling image, checkable, beside a preview; screenshots can be moved, deleted (to the Recycle Bin) or converted to the numbered naming from here. |
| **Files** | The resource's own folder as a file browser, with Reveal in the system's file manager. |
| **Checksums** | Each content file's last check, its date and result, with generate and verify. |
| **Log** | The app's log, narrowed to this resource. |
| **Save Preview** / **On Disk** | Hidden by default: exactly what a save would write, and the file as it is on disk right now. The pair is how you see a migration or a preserved unknown field with your own eyes. |
| **Content Images** | On a reference pack only, hidden by default: the pack's own images — inside its archives and loose in its folders — in rows justified to the panel's width and in natural order, each folder of images — loose, or inside an archive — opening with a banner naming its path under the pack (`/`, `foo/`, `foo.zip/`, `foo.zip/bar/`) and counting its images; a banner click folds its group away, and the banner of the group being scrolled through stays pinned at the top. Read-only — those images are checksummed content and the app never touches them. A click selects one and a status line names it; a double-click fills the window with it, like a screenshot, where `I` shows its name, pixel size and file size. Dragging an image out, or Ctrl+C, hands another app an unchanged copy named after the resource and the image's path in it, along with its pixels — from the grid and from any image filling the window. |

The fields themselves come from a **field toolkit** — one small class per kind of value (text, date,
rating, duration, size, tag list, path, …), each knowing how to display and edit it. A type's panels are
composed from that toolkit rather than hand-built: each plugin declares the fields its type has, so a
reference-images resource shows no tutorial duration and a collection shows the common fields alone. Any
field the type doesn't declare — and any field the toolkit has no entry for — falls back
to a generic row that carries the value verbatim. That fallback is what makes invariant 1 visible
instead of theoretical.

Four of those rows can **measure themselves**: the two sizes sum the resource's files, the two durations
add up how long its videos run, and a reference pack's image count opens its archives. Each shows what it
found *beside* the stored value rather than instead of it, so a disagreement — content deleted as it was
watched, an archive refreshed behind the app's back — is something you read before deciding, and a second
click is what stores it. Reading a video's length needs a media library the app carries, or an `ffprobe`
you already have; which one is a setting.

Which panels you had open, how you'd arranged them, and which file was in front are remembered per
resource and restored when you open it again.

Work that takes minutes runs on a **task queue** rather than in the window: one job at a time, each row
showing its progress and its own log, pausable, cancellable, reorderable, and written down so it survives
quitting. Checksums, `.tc` imports, scrapes and image downloads all run on it; an app-wide **Tasks** panel
shows the queue, beside an app-wide **Log**.

A **root catalog** is a `.rehuco` file naming the folders to catalog — its **roots**, each with a label. `Root Catalog` >
`New…` or `Open…` opens one, one at a time, in two app-wide panels — **Root Catalog**, which lists its roots, and
**Browsers**, which lists what its cache holds — and it is
reopened on start with the documents, under the same Session setting; a file written by a newer build opens read-only. `Root Catalog` > **Scan** puts one job per root on the
task queue. Each job walks its root and records every `.rehu` it finds, and every legacy `.tc` that no `.rehu`
covers, in a **`.rehudb`** cache. The cache sits in the machine's local cache folder and is named by the
`.rehuco`'s own id, so moving the `.rehuco` keeps its cache; it is only ever a copy, rebuilt by scanning again.
A table in the Browsers panel lists what the cache holds — authors, title, type, path, publisher, tags, release date, size, last update
and the file's format version, with the URL and a tutorial's or a reference pack's own fields a right-click on the
header away — and double-clicking a row opens that resource in Documents. A rename, save or deletion made in the app
changes just its row, in place. Each table has a **filter line**: free text and `field:value` tokens (`folder`,
`authors`, `tags`, `publishers`, `type`) narrow the rows, read from the cache again as the text settles. Clicking an
author's name in a document sets that author on it. The Browsers panel keeps any number of tables, each with its own
columns, filter and name: `Browsers` > `New Table Browser` starts one from a preset (the plain columns, or one type's
extra columns), and a browser can be renamed, cloned and deleted. They are kept by the app, not in the `.rehuco`.
The Root Catalog panel lists the roots, which the `Root Catalog` menu adds and removes, as a column view: one column
per open folder, with the details of the current row beside them — its checksum state where a checksum record covers
it, and, for a `.rehu` or a folder holding one, its URL and rendered description.

Selecting a row in a table, or a record in the Roots view, shows that resource in a preview panel in Documents, without
creating anything; a double-click on a table row opens it for real. `Root Catalog` > **Automatically preview the current rehu**, also
on the Root Catalog settings page, turns off the Roots view driving that preview. The tables always do.

The biggest user is **checksums**. Beside each resource sits a `.checksum` record of *when each of its
files was last checked and what the answer was* — not a manifest for an external tool, which is what lets
a run skip a file checked recently instead of re-hashing a terabyte to learn nothing. A document's toolbar
generates and verifies its own resource; `Tools` > `Sweep checksums…` points a run at a folder, finds every
resource under it, and checks only what has gone stale. Because each record is written as its resource
finishes, a sweep interrupted halfway carries on from where it was the next time it runs, with nothing
kept in memory to lose. How long a check stays good for, and which hash is used, are settings.

Details can also be **scraped** instead of typed: drop a page's URL on the editor and a scraper — built in
for ArtStation and Udemy, or a script of your own — fills the fields and fetches the screenshots, as an
ordinary edit you read before saving. The toolbar's **Search the Web** button goes the other way: it opens
your browser on a search for the words of the resource's location name, through an engine chosen (or added, as a name and a URL
template) on the Scrapers settings page.

## Where the pieces live

```text
packages/
├── rehuco-core/     the .rehu document, the .rehuco file and .rehudb cache, migrations, .tc conversion, checksums, the task queue — no GUI
├── rehuco-agent/    the desktop app: the field toolkit, the panels, the settings
├── rehuco-node/     a reserved name; nothing implemented
├── borco-core/      generic non-GUI utilities, on their way out of this repo
└── borco-pyside/    generic Qt widgets, likewise
```

The split that matters is **`rehuco-core` has no Qt in it**. Reading and writing a `.rehu` is not a GUI
concern, and keeping it that way is what would let something without a screen read a collection later.

## Coming from TutCatalog

The predecessors used a YAML sidecar, `info.tc`. rehuco reads that format and converts it: JSON parses
far faster at the sizes involved, which was the reason for changing. Conversion writes the `.rehu`,
renames screenshots to the current convention, and keeps backups it can roll back if any step fails. It
never writes `.tc` — the older format is read-only here. `Tools` > `Import Legacy Catalog…` converts a
whole folder tree at once, and `Tools` > `Conversion Backups…` discards the backups once you're satisfied.

## What does not exist yet

Everything above is implemented. None of the following is, and the design documents discuss all of it at
length, which is exactly why this section is here:

**A cache that follows the disk.** A change made to a `.rehu` outside the app shows in a table only after the next
scan, which re-reads just the records whose modification time or size changed. The other recursive walks — the checksum
sweep and the legacy import, over a folder you hand them — act as they go and remember nothing about what they found.

**No network beyond fetching a page you drop.** No node, no REST API, no discovery, no sync between
machines, no accounts or access rules, no web or tablet interface. `rehuco-node` is an empty package
holding its name.

**No playback and no progress tracking.** rehuco describes a tutorial; it does not play one.

Past what runs, the design reaches toward machines sharing a catalog; whether that is worth building is a question
the editor and the browser have to answer first.

## Where to go next

Only if you want depth on something specific:

- [README.md](README.md) — the document map: which numbered section lives in which file.
- [data-model.md](data-model.md) — the `.rehu` format and versioning in full.
- [plugins.md](plugins.md) — blocks, the field toolkit, and each resource type's surfaces.
- [implementation-plan.md](implementation-plan.md) — how the work is sliced, and what is deferred.
