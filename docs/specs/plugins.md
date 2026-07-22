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

### A plugin is two layers, and the lower one is non-GUI

**Every plugin has a non-GUI core layer, loaded by agent and node alike**, plus an optional GUI layer the agent alone
loads. This isn't a concession to testability — a node needs the lower layer anyway, since plugins own web rendering
([[plugins#core-vs-plugin]]'s table) and a node has no widgets to render with. The split also keeps `rehuco-core`
non-GUI, the same rule the field toolkit follows in reverse ([[plugins#field-toolkit]]).

- **Core layer (non-GUI)** — the plugin's **identity** (below), its block's schema and format version
  ([[plugins#plugin-blocks]]), and eventually its web rendering and its observers on core-field changes (the hook seam,
  [[daz3d-personal-database#authors-urls]]). Importable by `rehuco-node` with no Qt widgets in sight.
- **Agent layer (GUI)** — viewer/editor composition over the field toolkit, custom widgets, and custom actions (the
  Daz3D install action, [[plugins#daz3d-plugin]]).

**Identity is declared, not derived.** A plugin declares an ordered **key list**: the first entry is its **main key**,
the rest are **aliases** accepted on read and rewritten to the main key on write — a rename/migration path for free.
Deriving a key from a type name instead (e.g. snake-casing `ReferenceImages` → `reference_images`) cannot express a key
like `daz3d`, which is the snake_case of no type name at all; TutCatalog5 reached the same conclusion and declared key
lists in config (`base_item.py`'s `KEY`, `defaults.toml`'s `[types]`).

A resource's `type` **is** its block's key ([[plugins#plugin-blocks]]), so one key list serves both — it resolves a
legacy `type` spelling and the legacy block key it named, because they are the same token. tc4's capitalized `Tutorial`
/ `ReferenceImages` ([[acquisition-tooling#tc-to-rehu]]) are therefore aliases, and normalize on write.

**How this build knows a plugin exists** is a **registry**: the set of declared key lists installed here. It answers
only identity questions ("is this key a plugin I have, and what is its main spelling") — never which block is active,
which follows from `type` alone. The common core declares its identity the same way ([[data-model#rehu-format]]), which
is what reserves the name `core`: the registry already refuses two declarations claiming one spelling, so a plugin
cannot call itself `core` without a rule being written for it.

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

- [x] [#20: feat: A2.0 tracer — field toolkit + viewer/editor/both dock shell (text-field spine)](https://github.com/borco/rehuco/issues/20)

The field toolkit named in [[plugins#core-vs-plugin]] is a shared, non-plugin library the agent owns; plugins (and
declarative types) compose their viewer/editor from it. This section is its architecture and the
per-resource **viewer / editor / both** surface model that hosts it.

### §13.2.1 Field toolkit

[[[plugins#field-toolkit]]]

A **field** binds one logical value (a common-core field, or later a plugin sub-field) to the widgets
that show and edit it:

- **`Field`** — the base: a `type` selector ([[field-schema#field-types]]), a `name`, a display `label` (derived from
  the
  name when not given), a **viewer/editor `FieldsTab`** (the surface each belongs to), and two factories —
  `make_viewer()` and `make_editor()`. Each returns a **widget bundle** (`FieldViewerWidgets` /
  `FieldEditorWidgets`: the tab, a name `label`, an optional editor-only `misc` control, and the
  viewer/editor widget), any slot of which may be `None`. Viewer and editor are deliberately separate
  objects, not one widget in two modes ([[plugins#core-vs-plugin]]'s editor/viewer split). Each field maps
  to **one** editor; the multi-*surface* split (different fields in different docks, A2.6/#26) is the
  assembler's job — see `FieldsForm` — not a per-field list.
- **`FieldRegistry`** — maps a field `type` string to its `Field` subclass, so a type's field list
  resolves declaratively ([[plugins#core-vs-plugin]]: a declarative type is a field list over the toolkit). An
  unregistered type falls back to the unknown-field surface (A2.8/#28).
- **`FieldsForm`** — composes an ordered list of fields into a form (a `QFormLayout` of label + widget
  rows), asking each field for viewers or for editors depending on which surface it builds.

The toolkit lives in the **agent** (`apps/rehuco-agent/…/fields/`); `rehuco-core` stays non-GUI.
**Where each type's ordered field list is authored is not yet decided** — see the open question
([[appendices.open-questions#still-open]]). For A2.0 the tracer's field list is a hardcoded Python constant.

**Content fields vs. the location control — two different categories.** Almost every field is a piece of
**content**: a value stored *inside* the `.rehu` payload, bound bidirectionally to its editor. These
follow a **value-widget contract** — a `value` property, a `value_changed` signal, and a `set_value`
slot (as `DurationEdit` / `FileSizeEdit` / `DateEdit` already do) — and a scalar-or-list value fits it
directly (a multi-choice field is just `value: list[str]` + `value_changed`). Consolidating the
remaining content fields onto this contract (e.g. `text`'s inline `QLineEdit` becoming a value widget
that owns the echo guard) is A2.8/#28. The **`path` field is not
content**: it controls the resource's **identity** — the `.rehu`'s file name and possibly its parent
directory — not anything written into the payload. It rides the same `FieldsForm` purely for layout
convenience (label + middle control column + row alignment), which is why its owner constructs it out-of-band as a
*leading field* rather than from the type's field list. Its interface is therefore **not** a value: it is
a **command out** (a chosen name — `suggestion_clicked(str)`) plus **display-only inputs** (the
suggestions to show and the current name); its `location` display is a read-only projection of the path
that only changes when a rename actually succeeds (deferred to A5). So the value-widget contract is the
default for content fields, and the `path` field is not an exception to it but a different kind of
object outside its scope. The suggestions it displays are still derived from content fields
(`title` / `publisher` / …), so the naming domain logic belongs in a dedicated suggestion source, not in
the widget — the three roles stay separate: **compute** (a name-suggestion model) → **present/command**
(the `path` field) → **execute** (the view-model's rename).

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

The list/nested widgets and their group/subtype config land in a deferred slice (#97; the scope
outlived A2.3/#23 and A2.6/#26);
A2.0 ships only the leaf text field. A composite field still returns **one** editor widget from
`make_editor()` — a container holding its stacked subtypes — so owning child fields needs no base
change, and never a list of editors.

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
entry. The multi-source record-list *editor* is a deferred slice (#97; outlived A2.3/#23, A2.6/#26) — the view-model
is the seam it plugs into.

### §13.2.3 Viewer / editor / both surfaces

[[[plugins#viewer-editor-both]]]

Each open resource has a **viewer surface** and (for now) one **editor surface**, each built by a
`FieldsForm` over the same view-model, and each toggled independently:

- **viewer only**, **editor only**, or **both** — chosen by toggle actions; "both" is the live case
  above.
- The surfaces are hosted as docks inside a per-resource nested dock area ([[plugins#dock-shell]]), so "both" is two
  arrangeable docks, not a fixed split. See [[component-decomposition]] for the containment hierarchy this produces.

### §13.2.4 Document-dock shell

[[[plugins#dock-shell]]]

The agent hosts open resources in a **document-dock shell**: a `MainWindow` whose central area is a
QtAds dock-in-dock, with **one dock per open `.rehu`**. Opening a file adds its dock to the currently
focused document's area (tabbed) and focuses it; opening a file that is **already open focuses the
existing dock** rather than opening a second. Each document dock is itself a nested dock area holding
that resource's viewer/editor surfaces ([[plugins#viewer-editor-both]]). This replaces the A1 per-file window (#7) and
is the
same shell the catalog browser later opens viewers into ([[plugins#browsers]]). See [[sequence-open-document]] and
[[activity-open-document]] for this flow traced end-to-end.

The open-and-forward and single-instance semantics this shell realizes are owned by [[nodes#local-vs-swarm]] (local-file
mode) and [[nodes#single-instance]] (single-instance / file association); session persistence and the close guard are a
later slice (A2.1/#21). A nested surface toggle must carry the [[packaging-deployment#qml-regression]] closed-dock-size
workaround
(stash `splitterSizes` on `closeRequested`, reapply on `viewToggled(True)`).

## §13.3 Plugin blocks: keyed, versioned, single-active-type

[[[plugins#plugin-blocks]]]

> [!NOTE]
> **Implement the block save invariant with Opus, not the auto-switched Sonnet.** The active/inactive distinction, and
> especially the *claim-then-abandon-drops-but-never-claimed-foreign-carries* rule (the worked example below), is the
> subtle logic most likely to be implemented as the wrong-but-plausible "save the current type" — which silently deletes
> foreign blocks. Override to `/model opus` for this and check all four steps of the worked example.

Plugin fields are stored in **separate, uniquely-keyed blocks** (e.g. `tutorial:`, `reference_images:`, `daz3d:`), one
per plugin, each carrying **its own independent format version** (the per-plugin refinement of
[[data-model#schema-version]] — a plugin can evolve its block's schema without touching the common-field version or any
other plugin's). A plugin reads/writes only its own block and never needs to know the shape of another's. Each block's
key is its plugin's declared main key ([[plugins#core-vs-plugin]]); an alias spelling normalizes to it on write.

**Exactly one type, exactly one active block.** A `.rehu` declares a single `type`, whose value **is** the key of the
one block that is **active** (authoritative, editable by its plugin) — they are the same token, which is what lets a
reader classify blocks with no registry at all. Every other block in the file is **inactive**, regardless of whether a
matching plugin exists: a `reference_images:` block inside an `audiopack`-typed file is inactive and treated as unknown
even when the reference-images plugin is installed, because the file's type isn't reference-images. Conversely an
`audiopack:` block *is* active in that file even though no `audiopack` plugin is installed anywhere — **what is
installed never enters into it.** Plugin-installed-ness only affects whether the *active* block can be rendered richly
or must fall back to the generic editor; it never promotes an inactive block to active.

> [!NOTE]
> **Why "active", not "live".** This document already uses **live** for *real-time* — "live `both`"
> ([[plugins#view-model]]), live-updating viewers — and so does the code. A block that is authoritative and a widget
> that updates as you type are unrelated ideas, so the block model says **active** / **inactive** and leaves "live" to
> mean only "reacting now".

**Block persistence invariant (the rule that governs save):** on save, a block is written **iff**

- it is the **current active type's** block, **or**
- it is **foreign payload that has never been made active during this editing session** (carried verbatim, never
  silently dropped — a file is a custodian of blocks it doesn't own).

A block that **was made active this session and then abandoned** (the user switched to it, then switched away) is
**dropped on save** — by making it active and leaving it, the user asserted "this file is no longer that." All inactive
blocks (both kinds) remain **resurrectable from memory until the file is closed**, so switching type back and forth
within a session is non-destructive until save.

Worked example (type starts at `audiopack`, file also contains an untouched `reference_images` block):

1. Switch to `tutorial`: `audiopack` hidden + kept in memory but **dropped on save** (former active type, abandoned);
   `reference_images` shown as **unknown**, carried (never active). Save writes `tutorial` + `reference_images`.
2. Switch back to `audiopack`: in-memory `audiopack` revives; `tutorial` hidden.
3. Switch to `reference_images`: it becomes **active** — the plugin reconciles it (known sub-fields populate their
   editors; unknown sub-fields get the migrate/drop UI *within* the reference-images area). Save writes **only**
   `reference_images`.
4. Switch away to `tutorial`/`audiopack`: `reference_images` is now a former-active-and-abandoned block — no longer
   shown as unknown, just hidden, and **saving deletes it entirely** (contrast step 1, where the same block key was
   carried because it had never been active).

The same block key (`reference_images`) thus has opposite fates in steps 1 and 4, determined solely by **"was it ever
active this session."** Making a block active "claims" it; claiming-then-abandoning discards it; never-claiming carries
it.

**Safety net:** because making a block active arms its deletion-on-abandon (a user might switch to a type merely to
preview it), a save that drops a previously-foreign claimed block records the discard in the activity log
([[sync#overview]]) — "reference_images block discarded on date X" — so the *fact* of the drop is traceable even though the
values are gone, consistent with the document's "never silently lose reasoning" principle. Optionally the editor may
visually distinguish "former-identity, will drop on save" from "foreign, will carry" blocks.

## §13.4 Generic fallback editor for inactive / unknown blocks

[[[plugins#fallback-editor]]]

Inactive blocks (and an active block whose plugin isn't installed here) are shown via a generic fallback rather than
failing:

- **Unknown block** (whole plugin not the active type, or not installed): a labeled, collapsible section marked with
  *why* it's flagged — "not the current type" vs. "plugin not installed here" are different situations the user resolves
  differently. Default is carry-verbatim, with an explicit drop option.
- **Unknown field inside a known active block** (e.g. the installed plugin is an older version than the file's block):
  per-field UI to **drop or carry verbatim**. Renaming a recognized field belongs in the block's versioned migrations,
  where it is deterministic; the fallback editor does not manually map unknown fields. Undropped fields are carried
  untouched.
- Flagged items **stand out in the viewer**, labeled by provenance (newer-version-of-installed-plugin vs. plugin-absent
  vs. not-the-current-type) so the user knows whether the fix is "upgrade the plugin," "install it," or "this is just
  inactive payload."

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

### §13.5.1 Click-to-filter URL convention

[[[plugins#filter-urls]]]

Click-to-filter links share one wire format, so every linkified value uses the same parser:

```text
filter://<field>?name=<percent-encoded value>

filter://authors?name=Foo%20Bar
filter://tags?name=foo%20bar
filter://publishers?name=Example%20Publisher
```

- **One scheme, one query key.** The field is the URL's host part (always lowercase ASCII, so host normalization is
  harmless); the value always rides the `name` query parameter, percent-encoded, so any character a name can contain
  survives — including `/` and `,`, which a path- or delimiter-based encoding would trip over. The value is never
  encoded into the path or a bare query string: one `name=` parser serves every field.
- **Initial field set:** `authors`, `tags`, `publishers` — the three values [[plugins#browsers]] linkifies.
  `advertised_tags` and `extra_tags` share the single `tags` domain: clicking a tag filters on the tag regardless of
  which list it came from; the two-list split is an editing-side concept, not a filtering one.
- **Dormant until Milestone B.** The viewer renders external `http(s)` links from day one (an author entry's URL,
  [[field-schema#authors]]) but adds `filter://` anchors only once a browser exists to filter; until then the internal
  dispatch branch is a logged no-op seam. Link handling never enables the label's own external-link opening: one
  handler dispatches on scheme — `filter://` internally, validated `http(s)` to the system browser — so a `filter://`
  link can never leak to the OS, and no other scheme is ever followed.

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

## §13.9 Grouping-entity plugins: collection, author, learning path

[[[plugins#grouping-entities]]]

Three types share one template — **a grouping entity is a metadata-only resource**: `1 entity == 1 .rehu` with its own
`type`, no content files (the measured sizes are simply omitted), synced, retained, and rebuilt like any resource, with
its browser/editor contributed by its plugin ([[plugins#browsers]]). All three arrive with the catalog cache (Milestone
B's `.rehudb` — their browsers are what needs it), and none changes the v1 on-disk membership fields
([[field-schema#sources]]), which are already the reference mechanism this design builds on.

| | referenced by | natural home | own wrinkle |
| --- | --- | --- | --- |
| **collection** | member's `collections[]` | members' parent dir *when containment-shaped*, else the configured home | dual placement |
| **author** | credited name in `authors` ([[field-schema#authors]]) | configured home | alias aggregation |
| **learning path** | member's `learning_paths[]` | configured home / owner's per-user state | per-user, private/public |

- **Discovered vs. genuine.** An entity needs no document to exist: the membership entries on resources alone define a
  *discovered* entity — browsable, weightless, derived. A *genuine* entity has its own `.rehu`. The rule for which is
  which: **an entity document exists exactly when the entity has something of its own to say** — a description, an
  authoritative order, a public-visibility state. The browsers show the union, marked; adding a description to a
  discovered entity is what forces materializing it.
- **Materialization mints identity.** Creating the entity document is a deliberate act (like import,
  [[data-model#write-integrity]]): it mints the UUID, seeds the item list from the discovered members, and stamps the
  record timestamps. Nothing materializes as a side effect of browsing.
- **The entity document is the source of truth — but never retroactively.** When a genuine entity exists, its item
  list decides membership. A membership change is **one logical operation writing both documents** (the child's entry
  and the entity's list — the agent is a node client, each document keeps its single writer), never two independent
  field edits. A child-side entry the entity doesn't carry is pruned **only when the entity is known newer** (a
  version comparison, [[sync#overview]] — never blind precedence), the prune is a **logged event**, and a genuinely
  concurrent child-add vs. entity-edit is *surfaced*, not auto-lost — the same asymmetric-stakes rule as
  delete-vs-edit. A blind "strip on child save whatever the entity omits" would destroy legitimate child-side and
  offline additions the entity simply hasn't heard of yet.
- **Child entries stay even when the entity exists, as derived copies** — not for authority but for self-description: a
  resource checked out onto offline media must still know its memberships with no entity document in reach
  ([[architecture-design#why-distributed]]). Entity authoritative, child cached, repaired on reconcile — the same
  relationship as retained metadata copies ([[mounts-and-storage#durable-retention]]).
- **Ordering.** A discovered entity's order comes from the member-side `index` (the only data there is); a genuine
  entity owns the sequence in its item list, and member-side indexes become derived.
- **Description renders per membership.** tc4's motive for collection descriptions — write shared prose once, show it
  on every member — is served by rendering each membership's entity blurb in the member's viewer ("part of *X* — …",
  one section per membership). Nothing needs to pick *the* collection, so the multiple-membership ambiguity that
  killed description *inheritance* never arises.
- **Author specifics.** The entity's alias spellings and per-store URLs ride its own `sources`-shaped list
  ([[daz3d-personal-database#authors-urls]]); aggregating credited spellings into one entity uses the
  duplicate-review verdict flow ([[instances-and-dedup#duplicate-review]]) — propose, human verdict, never re-ask.
  Resources keep referencing authors by credited name; membership-by-identity (UUIDs on the references) follows the
  same later trajectory as collections ([[field-schema#deferred-items]]).
- **Learning-path specifics.** Paths are per-user with a private/public toggle ([[field-schema#per-user-shared]]). A
  *private* path likely stays pure per-user state with **the entity document minted at publication** — privacy by
  non-existence beats privacy by access rule — decided finally when the plugin is built. v1 (single-user, no
  entities) is unaffected either way.
- **Placement and discovery.** The directory tree is *never* the source of membership — a containment-shaped
  collection's `info.rehu` sitting in its members' parent directory is only that entity's natural home (and depends on
  the collection type being a scan non-boundary, [[data-model#scan-and-staleness]]). Every other grouping entity lives
  in the **configured creation directory** declared in `.rehuco` ([[mounts-and-storage#rehuco-scope]]). *Discovery* of
  existing entity documents needs no declared locations at all — it is type-based: the scanner finds them wherever
  they sit in any scanned root, so a swarm arriving with its own authors is just documents in its roots.

## §13.10 Shared capability worth extracting

[[[plugins#shared-capability]]]

"Follow tutorial" ([[plugins#tutorial-plugin]]) and the sketch-practice slideshow ([[plugins#refimages-plugin]]) both
want a **timed/sequential presentation** capability, just configured differently (tracked progress + notes/bookmarks vs.
a fixed-duration rotating display + a session log). Worth designing this as one shared core capability that plugins
configure, rather than reimplementing similar sequencing/timer logic independently in two plugins.
