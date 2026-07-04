# §13. Plugins

[[[plugins]]]

## Overview

[[[plugins#overview]]]

Resource types (tutorial, reference images, Daz3D, and future types) are implemented as **plugins**, loaded per
`.rehuco` declaration ([[mounts-and-storage#rehuco-scope]]). The core app provides default plugins for tutorials,
reference images, and Daz3D, but the architecture doesn't assume these are exhaustive.

## §13.1 Split between core and plugin-owned responsibility

[[[plugins#core-vs-plugin]]]

| Core (same for every resource type) | Plugin-owned (varies per type) |
| --- | --- |
| UUID, instance tracking, checksums, swarm sync | Schema extension — custom fields beyond the common set ([[data-model#rehu-format]]) |
| Tasks/job queue, node communication, REST plumbing | Viewer layout and behavior |
| Permissions/access grants | Editor layout and behavior |
| Dedup detection mechanics | Web rendering and interaction |
| `.rehuco` parsing and plugin loading | Custom actions with their own side effects (e.g. Daz3D install/uninstall) |
| The **field toolkit** (a shared library of reusable field widgets: text, switch, tag-list, date, rating, duration, size, choice, path, image-count, unknown, …) that plugins compose from | Browser columns + cover/shelf rendering for this type ([[plugins#browsers]]) |
| The **generic resource browser** (common columns) and the **viewer dock** shell | Search/index contributions (e.g. per-image tag search) |

A resource whose plugin isn't installed/loaded on a given machine should still degrade gracefully — at minimum showing
the common fields — rather than failing outright, since `.rehuco` (and therefore plugin availability) is per-machine.

**Plugins span a spectrum from declarative to code.** Two earlier ideas — a code-plugin model, and a TutCatalog5
experiment where `.rehuco` *declared* each type's fields from a fixed toolkit — are unified by layering rather than
choosing:

- **Declarative type** — a type defined purely as a *field list* over the shared field toolkit
  (text/switch/tag/date/rating/…), no code. Cheap to add (config, not programming), safe (zero code execution), but
  limited to what the toolkit offers. Good for simple types (e.g. a basic "3D object" with title/tags/format).
- **Code plugin** — a type that uses the same toolkit fields *plus* its own custom widgets and actions (the Daz3D
  install action, refimages redaction overlays, the sketch slideshow). Maximally flexible; the only thing that needs
  real code.

Both produce the same on-disk block ([[plugins#plugin-blocks]]) — whether a block's fields came from a declaration or
from plugin code is purely a rendering detail. This also answers a trust question
([[appendices.open-questions#still-open]]): **declarative types carry no code-execution risk; only code-plugins are a
trust/distribution surface.** "Add a simple new resource type" is a config task; code is needed only for behavior beyond
the toolkit.

## §13.2 Field toolkit and the viewer / editor / both surfaces

[[[plugins#toolkit-surfaces]]]

- [ ] [#20: feat: A2.0 tracer — field toolkit + viewer/editor/both dock shell (text-field spine)](https://github.com/borco/rehuco/issues/20)

The field toolkit named in [[plugins#core-vs-plugin]] is a shared, non-plugin library the agent owns; plugins (and
declarative types) compose their viewer/editor from it. This section is its architecture and the
per-resource **viewer / editor / both** surface model that hosts it.

### §13.2.1 Field toolkit

[[[plugins#field-toolkit]]]

A **field** binds one logical value (a common-core field, or later a plugin sub-field) to the widgets
that show and edit it:

- **`Field`** — the base: a `type` selector ([[field-schema#field-types]]), a `name`, a display `label` (derived from
  the
  name when not given), and two factories — `make_viewer()` and **`make_editors()` (plural)**. Viewer
  and editor are deliberately separate objects, not one widget in two modes ([[plugins#core-vs-plugin]]'s editor/viewer
  split); `make_editors()` is plural so one field can surface across more than one editor later (the
  multi-editor split, A2.6/#26) without changing the base.
- **`FieldRegistry`** — maps a field `type` string to its `Field` subclass, so a type's field list
  resolves declaratively ([[plugins#core-vs-plugin]]: a declarative type is a field list over the toolkit). An
  unregistered type falls back to the unknown-field surface (A2.8/#28).
- **`FieldsForm`** — composes an ordered list of fields into a form (a `QFormLayout` of label + widget
  rows), asking each field for viewers or for editors depending on which surface it builds.

The toolkit lives in the **agent** (`apps/rehuco-agent/…/fields/`); `rehuco-core` stays non-GUI.
**Where each type's ordered field list is authored is not yet decided** — see the open question
([[appendices.open-questions#still-open]]). For A2.0 the tracer's field list is a hardcoded Python constant.

**Fields compose — groups, lists, and nesting.** Beyond leaf fields (text, switch, …), a **group
field** is an ordered set of **subtype** fields, and a **list field** is a repeatable group. A
composite is configured declaratively: the admin names a **group** and lists the **subtypes** that
make up each item. A list renders each item as its subtypes stacked with their labels, plus per-item
controls — **`[+]`** (insert a new item after this one), **`[trash]`** (delete this item), and a
**`[grabber]`** handle for drag-to-reorder. Because a subtype may itself be a group or a list, fields
**nest to arbitrary depth**. Example: the multi-source editor ([[plugins#viewer-editor-both]], [[field-schema#sources]])
is a list whose item
group has three text subtypes:

```text
Publisher: [publisher edit]
Title:     [title edit]
URL:       [url edit]
```

The list/nested widgets and their group/subtype config land in a later slice (A2.3/#23, A2.6/#26);
A2.0 ships only the leaf text field, but the `Field` / `make_editors()` base is shaped so a field can
own child fields without a base change.

### §13.2.2 Reactive view-model

[[[plugins#view-model]]]

The surfaces never touch `RehuDocument` ([[data-model]]) directly. A thin **view-model** — a `QObject` wrapping
the pure document — exposes each field as a reactive property with a `…_changed` signal plus a
`dirty` flag; setting a field writes through to the document, marks dirty, and emits. This is what
makes **live "both"** work: an edit in the editor surface updates the view-model, whose signal the
viewer surface is bound to, so the viewer re-renders without the two surfaces knowing about each
other. Keeping the reactive layer in the agent preserves the core's non-GUI purity ([[plugins#core-vs-plugin]]).

Common-core `title` / `publisher` / `url` are attributes of a **source record** ([[field-schema#sources]]), and
`sources` is a list; the view-model exposes that list explicitly and, for now, edits the **primary**
entry. The multi-source record-list *editor* is a later slice (A2.3/#23, A2.6/#26) — the view-model
is the seam it plugs into.

### §13.2.3 Viewer / editor / both surfaces

[[[plugins#viewer-editor-both]]]

Each open resource has a **viewer surface** and (for now) one **editor surface**, each built by a
`FieldsForm` over the same view-model, and each toggled independently:

- **viewer only**, **editor only**, or **both** — chosen by toggle actions; "both" is the live case
  above.
- The surfaces are hosted as docks inside a per-resource nested dock area ([[plugins#dock-shell]]), so "both" is two
  arrangeable docks, not a fixed split.

### §13.2.4 Document-dock shell

[[[plugins#dock-shell]]]

The agent hosts open resources in a **document-dock shell**: a `MainWindow` whose central area is a
QtAds dock-in-dock, with **one dock per open `.rehu`**. Opening a file adds its dock to the currently
focused document's area (tabbed) and focuses it; opening a file that is **already open focuses the
existing dock** rather than opening a second. Each document dock is itself a nested dock area holding
that resource's viewer/editor surfaces ([[plugins#viewer-editor-both]]). This replaces the A1 per-file window (#7) and
is the
same shell the catalog browser later opens viewers into ([[plugins#browsers]]).

The open-and-forward and single-instance semantics this shell realizes are owned by [[nodes#local-vs-swarm]] (local-file
mode) and [[nodes#single-instance]] (single-instance / file association); session persistence and the close guard are a
later slice (A2.1/#21). A nested surface toggle must carry the [[packaging-deployment#qml-regression]] closed-dock-size
workaround
(stash `splitterSizes` on `closeRequested`, reapply on `viewToggled(True)`).

## §13.3 Plugin blocks: keyed, versioned, single-live-type

[[[plugins#plugin-blocks]]]

> [!NOTE]
> **Implement the block save invariant with Opus, not the auto-switched Sonnet.** The live/inert distinction, and
> especially the *claim-then-abandon-drops-but-never-claimed-foreign-carries* rule (the worked example below), is the
> subtle logic most likely to be implemented as the wrong-but-plausible "save the current type" — which silently deletes
> foreign blocks. Override to `/model opus` for this and check all four steps of the worked example.

Plugin fields are stored in **separate, uniquely-keyed blocks** (e.g. `tutorial:`, `refimages:`, `daz3d:`), one per
plugin, each carrying **its own independent format version** (the per-plugin refinement of [[data-model#schema-version]]
— a plugin can evolve its block's schema without touching the common-field version or any other plugin's). A plugin
reads/writes only its own block and never needs to know the shape of another's.

**Exactly one type, exactly one live block.** A `.rehu` declares a single `type`. That type — *not* which plugins happen
to be installed — names the one block that is **live** (authoritative, editable by its plugin). Every other block in the
file is **inert**, regardless of whether a matching plugin exists: a `refimages:` block inside an `audiopack`-typed file
is inert and treated as unknown even when the refimages plugin is installed, because the file's type isn't refimages.
Plugin-installed-ness only affects whether the *live* block can be rendered richly or must fall back to the generic
editor; it never promotes an inert block to live.

**Block persistence invariant (the rule that governs save):** on save, a block is written **iff**

- it is the **current live type's** block, **or**
- it is **foreign payload that has never been made live during this editing session** (carried verbatim, never silently
  dropped — a file is a custodian of blocks it doesn't own).

A block that **was made live this session and then abandoned** (the user switched to it, then switched away) is
**dropped on save** — by making it live and leaving it, the user asserted "this file is no longer that." All non-live
blocks (both kinds) remain **resurrectable from memory until the file is closed**, so switching type back and forth
within a session is non-destructive until save.

Worked example (type starts at `audiopack`, file also contains an untouched `refimages` block):

1. Switch to `tutorial`: `audiopack` hidden + kept in memory but **dropped on save** (former live type, abandoned);
   `refimages` shown as **unknown**, carried (never live). Save writes `tutorial` + `refimages`.
2. Switch back to `audiopack`: in-memory `audiopack` revives; `tutorial` hidden.
3. Switch to `refimages`: refimages becomes **live** — the plugin reconciles it (known sub-fields populate their
   editors; unknown sub-fields get the migrate/drop UI *within* the refimages area). Save writes **only** `refimages`.
4. Switch away to `tutorial`/`audiopack`: `refimages` is now a former-live-and-abandoned block — no longer shown as
   unknown, just hidden, and **saving deletes it entirely** (contrast step 1, where the same block key was carried
   because it had never been live).

The same block key (`refimages`) thus has opposite fates in steps 1 and 4, determined solely by **"was it ever live this
session."** Making a block live "claims" it; claiming-then-abandoning discards it; never-claiming carries it.

**Safety net:** because making a block live arms its deletion-on-abandon (a user might switch to a type merely to
preview it), a save that drops a previously-foreign claimed block records the discard in the activity log
([[sync#overview]]) — "refimages block discarded on date X" — so the *fact* of the drop is traceable even though the
values are gone, consistent with the document's "never silently lose reasoning" principle. Optionally the editor may
visually distinguish "former-identity, will drop on save" from "foreign, will carry" blocks.

## §13.4 Generic fallback editor for inert / unknown blocks

[[[plugins#fallback-editor]]]

Inert blocks (and a live block whose plugin isn't installed here) are shown via a generic fallback rather than failing:

- **Unknown block** (whole plugin not the live type, or not installed): a labeled, collapsible section marked with *why*
  it's flagged — "not the current type" vs. "plugin not installed here" are different situations the user resolves
  differently. Default is carry-verbatim, with an explicit drop option.
- **Unknown field inside a known live block** (e.g. the installed plugin is an older version than the file's block):
  per-field UI to **map to a known field, drop, or carry verbatim** — most useful here because the plugin *is* present
  and the user may know where a stray field belongs. Unmapped, undropped fields are carried untouched.
- Flagged items **stand out in the viewer**, labeled by provenance (newer-version-of-installed-plugin vs. plugin-absent
  vs. not-the-current-type) so the user knows whether the fix is "upgrade the plugin," "install it," or "this is just
  inert payload."

## §13.5 Resource browsers (per-type, with shelf/table modes)

[[[plugins#browsers]]]

The catalog is presented through **browsers**, which are the catalog-level counterpart to the plugin block model
([[plugins#plugin-blocks]]): just as a `.rehu` has common fields plus a type-specific block, a browser has common
columns plus type-specific columns.

- **Generic resource browser** — a table of *all* resources, columns = the common core ([[field-schema#resource-types]]:
  the primary source's title/publisher/url, released, `current_size`, updated). The type-agnostic baseline, and the
  fallback for any type whose plugin isn't installed (mirroring the generic field-editor fallback,
  [[plugins#fallback-editor]]).
- **Per-type browsers** — extend the generic browser with **plugin-contributed type-specific columns**: tutorials add
  duration / view-progress; reference-images adds image-count; etc. Contributing browser columns (and cover rendering)
  is a plugin responsibility ([[plugins#core-vs-plugin]]).
- **Two display modes** — tabular, or **cover/shelf view** (Calibre-style), per browser.
- **Clicking a resource opens its viewer dock** ([[nodes#local-vs-swarm]]).
- **Click-to-filter** (restored from TutCatalog4): tags, author, and publisher render as links in the viewer; clicking
  one sets the corresponding filter on the active browser (clicking an author shows all that author's resources, etc.).
  This couples the viewer dock to the browser's filter state — natural under the dockable-UI model — and was the primary
  filtering affordance in the usable older version.

## §13.6 Tutorial plugin

[[[plugins#tutorial-plugin]]]

- **Viewer** (triggered by double-clicking `.rehu` in File Explorer): read-only field display; rendered Markdown
  description; horizontal image strip with click-to-maximize, prev/next navigation, hideable thumbnail strip, ESC to
  close.
- **Editor**: field editing including the Markdown description; folder rename from the predefined-candidates list
  ([[data-model#rehu-format]]).
- **Follow** (a distinct mode from viewer/editor): sequential playback of the tutorial's files, recording watch progress
  and duration; note-taking (create/view/edit); bookmarking. Progress sync follows
  [[sync#overview]]/[[mounts-and-storage#node-handoff]].
- **Web**: search/browse tutorials the user has access to; follow a tutorial from the browser, with the same
  progress/notes/bookmarks behavior as the desktop "follow" mode.

## §13.7 Reference images plugin

[[[plugins#refimages-plugin]]]

Viewer/editor similar in shape to the tutorial plugin (no "follow" mode), with type-specific features:

- **Tagging at two granularities**: archive-level and per-image. Per-image tags are stored as app-managed mutable
  metadata alongside `.rehu`/screenshots (not inside the immutable, checksummed zip), keyed to images by index/filename
  — see [[data-model#image-meanings]] for the screenshot-vs-zip-content distinction and the stale-overlay warning when a
  zip is manually refreshed.
- **Non-destructive redaction**: rectangle/ellipse regions with an effect type (mosaic/blur/solid color), stored as
  app-managed metadata ([[data-model#image-meanings]]) and applied at render time — the original image inside the zip
  stays byte-identical and covered by the checksum manifest ([[data-model#checksums]]). A toggle controls whether
  redaction is shown; likely a per-user (not just per-device) preference.
- **Search**: tag-based filtering (select from existing tags, e.g. `female`, `back`, `3/4`) is straightforward.
  Free-text natural-language search (e.g. "3/4 view of male face") is harder and should be scoped as: a cheap fallback
  (fuzzy match against existing tags/synonyms) now, with a semantic/embedding-based approach as a possible later upgrade
  — not assumed solved by simple string matching.
- **Sketch-practice slideshow**: timed rotation (e.g. 20 sec/1 min/5 min per image) through a filtered image set, for
  drawing practice. Records a **session log** (ordered list of images shown, with timestamps/durations) distinct from
  any lifetime per-image view stats; the user can favorite/tag images from that session afterward, using the same
  per-image tagging mechanism as elsewhere — not a separate tagging system.
  - **Drawing comparison/critique** (exploratory, not committed): proposed as a two-stage pipeline — (1) deterministic
    facial/pose **landmark detection** run on both the reference image and the user's drawing, producing measurable
    deltas (eye height, symmetry, proportions), followed by (2) a cheap LLM call that narrates those numeric deltas in
    plain language. This is preferred over asking a vision-capable LLM to critique the images directly, which would be
    less reliably grounded in anything actually measured and more expensive per call. Caveat: landmark detectors are
    mature for photos but may not generalize well to loose hand-drawn sketches — this needs early prototyping against
    real sketches before being relied on. Treated as a v2/exploratory enrichment, not a dependency of the core
    sketch-practice feature.

## §13.8 Daz3D plugin

[[[plugins#daz3d-plugin]]]

Viewer/editor similar in shape to the others, plus a **custom action**: install/uninstall the plugin/asset into the
user's local Daz3D installation. Tracked per user *and* per box (i.e. "installed on which machine, by whom, when"),
since this is a system-integration side effect rather than a view/edit operation — it's the first concrete example
motivating "custom actions with tracked side effects" as a first-class plugin capability ([[plugins#core-vs-plugin]]),
not just schema/viewer/editor/web.

## §13.9 Shared capability worth extracting

[[[plugins#shared-capability]]]

"Follow tutorial" ([[plugins#tutorial-plugin]]) and the sketch-practice slideshow ([[plugins#refimages-plugin]]) both
want a **timed/sequential presentation** capability, just configured differently (tracked progress + notes/bookmarks vs.
a fixed-duration rotating display + a session log). Worth designing this as one shared core capability that plugins
configure, rather than reimplementing similar sequencing/timer logic independently in two plugins.
