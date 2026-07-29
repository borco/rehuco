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
| **Viewer** | The resource read-only: its fields, the rendered Markdown description, and its screenshots as a thumbnail strip. Clicking a thumbnail fills the window with it; arrow keys or the wheel move through the set. |
| **Main Editor** | The same fields, editable, plus the type selector that decides which block is active. Its path row offers names built from the record — title, publisher, authors, year — and picking one renames the resource on disk: the folder for a directory-scoped resource, and for a standalone one every file named after it, archives and screenshots alike. |
| **Description** | The Markdown description in its own panel, so prose can be written with room. |
| **Images** | Which screenshots the strip shows: every sibling image, checkable, beside a preview. |
| **Save Preview** / **On Disk** | Hidden by default: exactly what a save would write, and the file as it is on disk right now. The pair is how you see a migration or a preserved unknown field with your own eyes. |

The fields themselves come from a **field toolkit** — one small class per kind of value (text, date,
rating, duration, size, tag list, path, …), each knowing how to display and edit it. A type's panels are
composed from that toolkit rather than hand-built: each plugin declares the fields its type has, so a
reference-images resource shows no tutorial duration and a collection shows the common fields alone. Any
field the type doesn't declare — and any field the toolkit has no entry for — falls back
to a generic row that carries the value verbatim. That fallback is what makes invariant 1 visible
instead of theoretical.

Which panels you had open, how you'd arranged them, and which file was in front are remembered per
resource and restored when you open it again.

## Where the pieces live

```text
packages/
├── rehuco-core/     the .rehu document, its blocks, migrations, atomic I/O, legacy .tc reading — no GUI
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
never writes `.tc` — the older format is read-only here.

## What does not exist yet

Everything above is implemented. None of the following is, and the design documents discuss all of it at
length, which is exactly why this section is here:

**No database, no scanning, no search.** rehuco opens files you point it at, one at a time. There is no
library view. `.rehudb` is a name in the design, not a file any code writes.

**No network, in any form.** No node, no REST API, no discovery, no sync between machines, no accounts
or access rules, no web or tablet interface. `rehuco-node` is an empty package holding its name.

**No playback and no progress tracking.** rehuco describes a tutorial; it does not play one.

The next thing worth building is a **browser** — a view over a folder of resources, backed by a cache
that can always be rebuilt from the `.rehu` files themselves, so a collection can be looked through
instead of opened one file at a time. Past that, the design reaches toward machines sharing a catalog;
whether that is worth building is a question the editor and the browser have to answer first.

## Where to go next

Only if you want depth on something specific:

- [README.md](README.md) — the document map: which numbered section lives in which file.
- [data-model.md](data-model.md) — the `.rehu` format and versioning in full.
- [plugins.md](plugins.md) — blocks, the field toolkit, and each resource type's surfaces.
- [implementation-plan.md](implementation-plan.md) — how the work is sliced, and what is deferred.
