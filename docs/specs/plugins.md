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
the rest are **aliases** accepted on read and rewritten to the main key on write *when that key is unoccupied* — a
rename/migration path for free (an alias block whose main key is already taken is left under its own spelling, #137).
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

### A plugin declares its own badge colors

[[[plugins#badge-colors]]]

Identity carries **presentation** too: a plugin may declare a **badge background** and **badge text** color, each a
plain hex string (`#1E88E5`) rather than a Qt object, so they stay in the non-GUI core layer and travel with the
declaration from wherever the plugin comes from — built-in today, an external package later (#83). The agent's type badge
paints a resource's type chip with them; a **node ignores them entirely**. Keeping the colors on the declaration rather
than deriving them in the agent is the same "a plugin owns how it presents" rule the two-layer split rests on: the agent
renders, the core declares.

Either color is **optional, and an undeclared one resolves against the live theme, not a hardcoded default** — an absent
background falls back to the palette's selection background (Qt's `Highlight` role), an absent text to the selection text
(`HighlightedText`), re-resolved on every palette change so a badge stays legible when the OS flips light/dark. A plugin
that declares nothing still gets a sensible, theme-consistent badge; declaring only a background (the common case) lets
the theme own the text color. A type whose plugin **isn't installed here** has no declaration to consult, so its badge
takes exactly that theme fallback — the not-installed path ([[plugins#plugin-blocks]]) reuses the same `None`-resolution
rather than inventing a placeholder color.

The built-in declarations (background only; all three take the theme's selection text):

| plugin | badge background |
| --- | --- |
| `tutorial` | `#1E88E5` (Blue 600) |
| `reference_images` | `#8E24AA` (Purple 600) |
| `collection` | `#00897B` (Teal 600) |

`daz3d` ([[plugins#daz3d-plugin]]) has no declaration at all — it is future work — so a `daz3d:` block exercises the
not-installed fallback for real rather than hypothetically. These per-type category colors are independent of the app's
brand palette: a badge names *which resource type* this is, not the product.

## §13.2 Field toolkit and the viewer / editor / both surfaces

[[[plugins#toolkit-surfaces]]]

- [#20: feat: LocalEdit2.0 tracer — field toolkit + viewer/editor/both dock shell (text-field spine)](https://github.com/borco/rehuco/issues/20)

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
  to **one** editor; the multi-*surface* split (different fields in different docks, LocalEdit2.6/#26) is the
  assembler's job — see `FieldsForm` — not a per-field list.
- **`FieldRegistry`** — maps a field `type` string to its `Field` subclass, so a type's field list
  resolves declaratively ([[plugins#core-vs-plugin]]: a declarative type is a field list over the toolkit). An
  unregistered type falls back to the unknown-field surface (LocalEdit2.8/#28).
- **`FieldsForm`** — composes an ordered list of fields into per-tab **3-column grids** (a `QGridLayout` laid out
  label | misc | content, with header-pinning), asking each field for viewers or for editors depending on which
  surface it builds. It also **routes the fields' outward-facing signals to the owner**, matched by structural
  protocol rather than by field type: `StatusReporter` (the `authors` viewer's hovered-link URL) and
  `ImageActivator` (the `images` strip reporting a clicked screenshot). This is the toolkit's standing rule —
  **a field decides *that* something happened, never *what* the app does about it**: it does not reach for a status
  bar, a window, or a settings value it doesn't own. The owner (`DocumentSubDocks`) collects such fields on every form
  it builds, rebuilds included, and acts.

The toolkit lives in the **agent** (`packages/rehuco-agent/…/fields/`); `rehuco-core` stays non-GUI.
**Which fields a type has is declared by its plugin** ([[field-schema#resource-types]], #195) — names only, so the
declaration stays non-GUI and a node can read a block's shape from it; the agent maps each name to a toolkit type. A
type whose plugin isn't installed here declares nothing, which is already the fallback path
([[plugins#fallback-editor]]). **Where each type's *ordered* list is authored is still not decided** — see the open
question ([[appendices.open-questions#still-open]]); the order is a hardcoded Python list spanning every type,
filtered per type.

**Content fields vs. the location control — two different categories.** Almost every field is a piece of
**content**: a value stored *inside* the `.rehu` payload, bound bidirectionally to its editor. These
follow a **value-widget contract** — a `value` property, a `value_changed` signal, and a `set_value`
slot (as `DurationEdit` / `SizeRow` / `DateEdit` already do) — and a scalar-or-list value fits it
directly (a multi-choice field is just `value: list[str]` + `value_changed`). Consolidation of the
remaining content fields onto this contract (e.g. `text`'s inline `QLineEdit` becoming a value widget
that owns the echo guard) shipped in LocalEdit2.8/#28. The **`path` field is not
content**: it controls the resource's **identity** — the `.rehu`'s file name and possibly its parent
directory — not anything written into the payload. It rides the same `FieldsForm` purely for layout
convenience (label + middle control column + row alignment), which is why its owner constructs it out-of-band as a
*leading field* rather than from the type's field list. Its interface is therefore **not** a value: it is
a **command out** (a chosen name — `suggestion_clicked(str)`) plus **display-only inputs** (the
suggestions to show and the current name); its `location` display is a read-only projection of the path
that only changes when a rename actually succeeds. So the value-widget contract is the
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

The **record-list machinery** ships as `ItemListEditor` (`borco_pyside.widgets`): a view over a model
plus the insert/edit/delete/reset and top/up/down/bottom action columns, with the keys armed on the
view alone. Its two clients are the settings pages' `StringListEditor` and the `authors` record rows
(#97). Declarative group/subtype *config* — a composite an admin describes rather than one a field
builds — is still unbuilt, as is nesting past one level. Drag-to-reorder ships in the card list
(`CardListEditor`, #390), which the `sources` editor uses (#391). A composite field
returns **one** editor widget from
`make_editor()` — a container holding its stacked subtypes — so owning child fields needs no base
change, and never a list of editors.

**A field may bind more than one model field.** `Field.names` lists them (just its own `name` for nearly
every field); the assembler resolves one binding per name and hands the field all of them, so a field
still never sees the model. That is what lets the two sizes be **one** composite over `original_size` and
`current_size` sharing a single scan (#232), and the two durations be the same over `original_duration`
and `current_duration` (#233) — each merge exists because both halves are the same scan, differing only
in when the user accepts it, so two independent rows meant running it twice for the same answer. The
**editor** is one widget holding its own grid, per the rule above; the **viewer** is not bound by it — a
viewer row carries no internals to align — so such a field still contributes one plain labeled row per
name. A pair spec whose type declares only one of its names is narrowed to that name rather than refused.

### §13.2.2 Reactive view-model

[[[plugins#view-model]]]

The surfaces never touch `RehuDocument` ([[data-model]]) directly. A thin **view-model** — a `QObject` wrapping
the pure document — exposes each field as a reactive property with a `…_changed` signal plus a
`dirty` flag; setting a field writes through to the document, marks dirty, and emits. This is what
makes **live "both"** work: an edit in the editor surface updates the view-model, whose signal the
viewer surface is bound to, so the viewer re-renders without the two surfaces knowing about each
other. Keeping the reactive layer in the agent preserves the core's non-GUI purity ([[plugins#core-vs-plugin]]).

**One view-model per open resource, app-wide** (#375). The same bindings that keep two surfaces of one document in
step keep *two hosts* in step: a resource shown both in a Documents dock and in the Documents preview, or in two docks,
([[plugins#browsers]]) is **one** view-model held by both, so an edit in either shows in the other before anything is
saved. A registry keyed by path owns the view-models and hands the same one to every holder; a view-model lives until
its last holder lets go, and the unsaved-changes prompt belongs to that last release, not to closing one of several
views. A rename relocates every held view-model at or beneath the renamed paths ([[mounts-and-storage#out-of-band]]).

Common-core `title` / `publisher` / `url` are attributes of a **source record** ([[field-schema#sources]]), and
`sources` is a list; the view-model exposes it top-first, the top entry being the **primary**, and the Main
Editor edits it as **one card per source** (Title, URL, Publisher) on the reusable card list
(`borco_pyside.widgets.CardListEditor`, #390, #391). The viewer keeps its Title, Publisher and URL rows,
showing the primary.

### §13.2.3 Viewer / editor / both surfaces

[[[plugins#viewer-editor-both]]]

Each open resource has **viewer surfaces** and **editor surfaces**, every one built by a `FieldsForm`
over the same view-model and toggled independently:

- Two viewer surfaces — **Main View** (the location, the type-declared record fields, and the
  unknown-field / inactive-block fallback rows; the type badge is not a field surface at all but the
  lead item of the document's own toolbar, so it reads whichever docks are open) and **Description
  View** (the image strip, then
  the rendered Markdown description filling the rest of the height). They were one surface holding all
  of it until the two tall, scrolling halves were split apart from the record fields they sat around.
- Three editor surfaces — **Main Editor**, **Description**, and **Images**.
- **viewer only**, **editor only**, or **both** — chosen by toggle actions; "both" is the live case
  above. A typed resource **opens as a reader**: the two viewers are shown side by side, Main View left
  and Description View right, and every editor starts hidden behind its toggle. A resource with **no
  type** — brand new, about to be filled in — opens the other way round, on the Main Editor alone. A
  user who prefers otherwise saves the arrangement they want as that type's default layout, "(no type)"
  included, which every document of the type with none of its own then opens into.
- The surfaces are hosted as docks inside a per-resource nested dock area ([[plugins#dock-shell]]), so "both" is
  arrangeable docks, not a fixed split. See [[component-decomposition]] for the containment hierarchy this produces.

### §13.2.4 Document-dock shell

[[[plugins#dock-shell]]]

The agent hosts open resources in a **document-dock shell**: a `MainWindow` holding a **Documents** dock — an ordinary
QtAds dock the user hides and shows like the Log and Tasks docks, not the central widget — whose own nested dock
manager holds **one dock per open `.rehu`**. Opening a file shows the Documents dock if it is hidden and raises it,
then adds the new dock to the currently
focused document's area (tabbed) and makes it current — what was just opened is on screen whatever the layout was;
opening a file that is **already open focuses the
existing dock** rather than opening a second. Each document dock is itself a nested dock area holding that resource's
**sub-docks** — the word for a dock inside a document dock, three managers deep
([[appendices.qt-ads#focus-highlighting]]). **The sub-dock set is declared per resource type** —
[[plugins#core-vs-plugin]] applied to docks: the **common shell** every document has — the two viewers, main view
and description view; the main editor, the description and the images editors; plus the hidden-by-default
inspection set — save preview, on disk, log, checksums, files ([[plugins#files-subdock]]) — and then **the type's
own**: a reference pack adds content images (the browse over its archived and loose images,
[[reference-images#modes]]), a tutorial
will add its player, a collection adds nothing. The images sub-dock doubles as the drop target of
[[acquisition-tooling#drag-drop-aids]]. The surfaces are the viewer/editor pair ([[plugins#viewer-editor-both]]).
This replaces the LocalEdit1 per-file window (#7) and is the same shell the catalog browser later opens viewers
into ([[plugins#browsers]]). See [[sequence-open-document]] and [[activity-open-document]] for this flow traced
end-to-end.

A layout follows the type: the **default layout** is saved per type with no inheritance across types, and a
document opened with no stored layout of its own gets its type's — a session-restored document gets **what was
stored**, and only if that cannot restore does the type's current layout step in. The set follows the type: built
when the type is first known — at open, or at a session-restore placeholder's deferred first read — and swapped by a
later type switch in the editor, which closes and removes the outgoing type's own docks, their toolbar toggles with
them, and adds the incoming type's hidden. A switch applies no layout — the docks the user is switching from stay as
they are; the layout button afterwards applies the *new* type's default. The one exception is **leaving (no type)**:
the empty type is a type like any other here, with its own saved default and an as-built layout of the Main Editor
alone, and that layout only ever meant "no type yet" — so picking a type for a type-less document applies the new
type's default (saved, else as-built). A session-restored document's stored layout still wins over this: its type
arriving from the deferred first read is not a switch. A layout restores onto a dock set other than the one it was
written against: a dock it names that isn't built is skipped, and a built dock it never names is put back hidden
where it always lives (QtAds would otherwise leave it area-less, to open floating). That tolerance is what retires
the hand-bumped layout version: adding a dock to one type no longer resets anyone's layouts.

The open-and-forward and single-instance semantics this shell realizes are owned by [[nodes#local-vs-swarm]] (local-file
mode) and [[nodes#single-instance]] (single-instance / file association); session persistence and the close guard are a
later slice (LocalEdit2.1/#21). A nested surface toggle must carry the [[packaging-deployment#qml-regression]] closed-dock-size
workaround
(stash `splitterSizes` on `viewToggled(False)` — `closeRequested` never fires on a toggle-hide — reapply on
`viewToggled(True)`).

**The sub-docks are one reusable piece.** The document sub-docks, the document toolbar and the layout button are built
into whatever dock manager hosts them and can be torn down and rebuilt there for another resource (#380), not something
only a Documents dock owns. A host names its own namespace for the **per-type default layouts** it keeps, so a layout
saved in one never changes how another opens that type. Today the Documents dock is the only host; the browsers and the
Roots view show a selected resource through its preview, below, and hold no document sub-docks of their own (#381).

**The preview dock.** Documents holds at most one **preview** dock (#39), the way an editor's file explorer opens a
file in a preview tab. Showing a `.rehu` open in an ordinary dock
focuses that dock; showing one the preview already shows does nothing; showing any other puts it in the preview, made if
there is none. The preview **switches in place**:
the same dock, the old document's sub-docks torn down and the next one's built into the same manager, the old model
released — the rebuild above, inside a document dock. It is **promoted** to an ordinary dock, in place, by
a double-click on its title, or by being asked for another `.rehu` while it has unsaved changes — nothing is lost or
asked, and the other `.rehu` goes to a new preview. An edit alone does not promote, nor a saved one. Its title is the
document's label in italic; its object name is `Preview-<n>`, numbered per preview because a promoted dock keeps the
manager registry entry it was added under ([[appendices.qt-ads#dock-registry-keys]]). It is **transient**: never in the
session, and in `Open recents` only once promoted. Each type's preview remembers **its own layout** under
`preview_layout/<type>`, captured whenever the preview stops showing that type (a switch, a promotion, its close, app
exit) and written at exit; a type with none opens with its default layout. That layout is implicit: the Layout button
in a preview acts on the type's default layout, as in any document dock.

### §13.2.5 The files sub-dock

[[[plugins#files-subdock]]]

Every document dock carries a **Files** sub-dock, hidden by default beside the inspection set: a browsable table over
the resource's own folder — name, a checksum verdict, what the file is to the resource, size and modified — so what the
app's own renames, conversions and drops did to the folder can be read without leaving it.

**It is confined to the resource's own folder.** The root is the record's directory, and there is no way above it: a
`..` row appears only while the reader is below the root, and both it and the toolbar's up action stop there. Going up
would leave the resource entirely, and a general file manager is not what this is — the neighbouring folder a reader
wants is reached by opening the resource that owns it, which is what the foreign-record rows below are for. The
toolbar also carries **home**, the one-click jump back to the record's own directory from any depth; it and up take the
same condition and are both greyed at the root, and greyed together for a document with no folder to go home to. Up
and the `..` row wear one glyph, being one act reached two ways, and deliberately not the glyph the folder rows wear.

**What a row lets you do is decided by what the file is to this resource** — the roles
[[data-model#resource-scoping]]'s coverage rules already name, asked one directory at a time rather than as the
recursive *is this content* the size scan and the checksums ask. Three kinds are shown but **not** actionable, each a
deliberate refusal: the resource's **own record**, because that is the document already on screen; a **foreign
record's sidecar**; and **content a foreign record covers**, because its screenshots are curated in *its* images dock
and its content is covered by *its* checksums, so there is nothing here to do with either but see that it is there. The
refusal lives in the model's own item flags, so such a row cannot be selected or activated at all rather than being
activated and ignored.

The four things a double-click *can* do are each routed out of the sub-dock rather than done in it, since it knows what
a file **is** and none of what to do about it:

- **a folder** — walked into, unless the listing is covered by a directory-scoped record that is not the browsing
  document's, in which case everything beside it is that record's wholesale (#254) and its own row is the way in.
  The predicate is deliberately *directory-scoped* rather than *any record*, which settles three cases at once. A
  **directory-scoped resource browsing its own folder always keeps its subfolders**: it covers that ground, so
  nothing sitting beside it can take them — not a file-scoped `foo.rehu`, which claims only its same-stem siblings,
  and not a legacy `info.tc` a conversion left behind, which *is* the same resource under its old name. A folder
  holding several file-scoped records and **no** `info.rehu` keeps its subfolders too, for the same reason read the
  other way: no record there claims the ground. And a **file-scoped** `foo.rehu` sharing a folder with an
  `info.rehu` does not cover it, so its subfolders belong to that record — as do those of any subdirectory holding
  a record of its own.
- **another resource's record** — opened, or focused if it is already open, through the **window's** ordinary open
  route, so it is resolved, the documents area is revealed and the file joins `Open recents` exactly as a menu open
  would ([[plugins#dock-shell]]).
- **this resource's checksum record** — a *Verify All* over this resource, the same action its own toolbar carries
  ([[data-model#checksums]]), so there is one definition of what that checks. Inert where the document was built with
  no queue to enqueue a run on.
- **an image** — opened maximized through the same owner-routed activation the strip uses
  ([[plugins#tutorial-plugin]]), but against **every image in the browsed folder**, curated or not: this is a view of
  the folder rather than of the lightbox's set, and a screenshot someone curated out is exactly the one they may want
  to look at here ([[data-model#image-meanings]]).

Anything else is handed to the system's default handler.

**The checksum column reports what *this* record claims, and nothing else.** Seven verdicts and an empty cell: nothing
at all for the record, a sidecar, a folder, content another record covers, or every file at all when this record
cannot be read — this record makes no claim there, which is different from a claim of ignorance, and reading the
neighbour's record to answer for it would make a glyph mean *somebody verified this*. Content this record holds no
hash for says so (whether the resource has no `.checksum` at all or that record skips the file — both are *nothing is
recorded about these bytes*, and the remedy for both is the same generate). Four are matched-or-not crossed with
fresh-or-stale, and the fresh/stale split is the **run's own** staleness rule rather than an opinion formed in the
GUI: a *current* glyph means exactly *a verify would skip this file*, and a *stale* one means exactly *it would not*.
The last two are entries resting at `unexpected` and at `malformed` (#303), each its own glyph with no stale pair:
`unexpected` is a report state a sweep ordinarily rewrites, so an entry resting there was written by something other
than this app's runs, and `malformed` means this build has made **no claim** about the bytes — drawing it as a
mismatch would assert a check that never happened, and drawing it as missing would invite a generate that overwrites
a neighbour's entry. **The mapping from an entry to a glyph is one function** the checksum dock (#244) reads too, so a
file's verdict looks the same in both. One `.checksum` read per refresh, whatever the folder holds.

It **refreshes when shown and on demand** — `F5` and a refresh button, each refreshing only this sub-dock — plus
whenever the app itself changes something beneath the resource's folder: a rename, a save, a conversion, a screenshot
moved or deleted, a checksum run finishing ([[mounts-and-storage#out-of-band]]). Never in between. Each read is
applied **in place**, so a selection and the scroll position survive it, and a rename or convert keeps the reader in
the same subfolder rather than sending them back to the top. Deliberately **not `QFileSystemModel`**: that model installs a file-system watcher that holds handles open on
Windows, and a held handle is exactly what makes a rename or a delete of the resource's own files fail — the app would
be locking what it is about to move. The same reasoning already keeps a watcher out of the node
([[mounts-and-storage#out-of-band]]). A plain listing costs one `scandir` per refresh and holds nothing between them,
and it runs off the GUI thread: neither that nor the record read is slow, and either blocks for the share timeout when
the mount is away ([[mounts-and-storage#offline-mounts]]) — an unreachable folder says so rather than drawing an empty
table over it (#245).

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
key is its plugin's declared main key ([[plugins#core-vs-plugin]]); an alias spelling normalizes to it on write **only
when the main key is unoccupied** — if a block already holds the main spelling, the alias block stays foreign under its
own key and its `type` normalizes only together with its block (#137).

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

One thing a switch *does* write, deliberately: the newly-active block is **normalized on activation**, the same
normalization the block a document opens at receives — a JSON `null` under a known optional scalar is dropped, since
`null` is the on-disk spelling of absent and the active block must never carry one into a save
([[field-schema#deferred-items]]). Normalizing earlier would edit payload the document has no standing over — activation
is what gives it that standing, so the normalization attaches to the same moment as the claim. Nothing readable changes:
the key read as `None` before and reads as `None` after, and revert re-reads the file.

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
values are gone, consistent with the document's "never silently lose reasoning" principle. The editor **visually
distinguishes** "former-identity, will drop on save" from "foreign, will carry" blocks (one of the four provenance
flags it labels, [[plugins#fallback-editor]]).

## §13.4 Generic fallback editor for inactive / unknown blocks

[[[plugins#fallback-editor]]]

Inactive blocks (and an active block whose plugin isn't installed here) are shown via a generic fallback rather than
failing:

- **Unknown block** (whole plugin not the active type, or not installed): a labeled, collapsible section marked with
  *why* it's flagged — "not the current type" vs. "plugin not installed here" are different situations the user resolves
  differently. Default is carry-verbatim, with an explicit drop option.
- **Unknown field inside a known active block** (e.g. the installed plugin is an older version than the file's block):
  per-field UI to **drop or carry verbatim** (carry is the default). A stray field that is really a *renamed* known one
  is repaired by a migration-chain step, not an in-editor remap (#85's interactive "map to a known field" was closed
  not-planned — renames go in migrations). Undropped fields are carried untouched.
- Flagged items **stand out in the viewer**, labeled by provenance (newer-version-of-installed-plugin vs. plugin-absent
  vs. not-the-current-type vs. claimed-then-abandoned-this-session) so the user knows whether the fix is "upgrade the
  plugin," "install it," "this is just inactive payload," or "switch back to this type before saving to keep it."

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

### §13.5.1 The Root Catalog dock

[[[plugins#rehuco-dock]]]

Two top-level docks, first on the action bar and tabbed beside Documents, show one opened `.rehuco` — a *root
catalog* ([[data-model#local-file-trio]], #377, #461): the **Root Catalog** dock holds its roots and the
**Browsers** dock its browsers, each named as its menu is, each with its own `View` toggle, and both revealed when a
catalog is opened. The word *collection* is not used for it: that is a resource type ([[plugins#grouping-entities]]).
**Neither dock has a toolbar.** The Root Catalog dock's title bar holds *Refresh* and the Browsers dock's *New Table
Browser*; *Scan*, *Add Root* and *Remove Root* are entries of `Root Catalog` and *Rename Browser* of `Browsers`, the
rare actions being the menu's ([[appendices.code-conventions#command-surfaces]]). **One object owns the open file
and its cache** — the catalog — and both docks read it and hear from it when it changed; neither holds the file.

- **The Root Catalog dock** (#378) — a column view: the first column is the `.rehuco`'s roots by label
  ([[mounts-and-storage#rehuco-scope]]), each further column one folder's listing, drawn like the files sub-dock
  ([[plugins#files-subdock]]) but with no `..` row, which a column view has no use for. It is **navigation, not
  membership**: what the catalog holds is still decided by records, never by the tree ([[plugins#grouping-entities]]).
  The `Root Catalog` menu holds **Scan**, **Add Root** and **Remove Root**; a root's context menu holds, in three
  groups, the folder filter and Open in file explorer; the four moves — top, up, down, bottom, with the ordering
  icons the settings lists use but not their list editor, whose inline insert, rename, duplicate and reset have no
  meaning for a root; and, last and apart, Remove Root. A root row is two lines, its name and under it its folder,
  smaller and fainter and elided to fit, with its storage glyph centred beside both. Its details pane has no move buttons, the grip being the way to move one.
  A folder's menu holds the folder filter and the folder's rehu: **Open associated rehu** when its `info.rehu` (or `info.tc`) is there, **Create rehu**
  — a new unsaved record, opened in Documents — when it is not ([[data-model#resource-scoping]]). A checksum file's menu
  also offers **Verify checksums**, which queues a verify of the `.rehu` that shares its name — the same job the
  Checksums dock queues — and is off while there is no such `.rehu`. A file's menu
  offers **Open in external app** and the same pair for the `.rehu` that shares its name, and a `.rehu` or `.tc`
  file's offers **Open**. The first entry of a menu is the row's **default action**, drawn bold: what a double-click
  runs. A rehu is never created by a double-click, so a folder with none has no default. A **details pane** beside
  the columns shows the current row, whatever it is: name, type, size, when it changed, how much a folder holds and
  where it is (elided to fit), from what the listing already read, and a thumbnail for an image read off the GUI
  thread. **Below the details is a button for every entry of the row's context menu**, in its order, the default in
  bold; **below the buttons, for a `.rehu` or `.tc` row or a folder that has one, what the record says**: its URL as
  a link (elided, opened in the system's browser) and its description, rendered as the Description dock renders it
  and scrolling in the height the pane has left, under a line — read from the file off the GUI thread on each
  selection, never from the cache, and dropped if the row has changed by the time it lands; a field the record
  lacks is left out, a record with neither shows no line; a folder's menu and buttons also hold **Open in file explorer**, and its create entry is named for what it
  would start, `Create info.rehu`. `QColumnView`'s own preview column is collapsed. A root can also be
  **dragged to another place** by the grip band of dots at the left of its row — the same handle a card list has, with
  its open-hand cursor and its *Drag to reorder* tooltip — and only by it, so a click anywhere else on the row just
  selects. It is dragged as a card of a card list is, by the same shared code: the root leaves its place, which
  becomes a shadow; the one shadow follows the pointer to where the root would land, the other roots closing up around
  it; leaving the list puts it back at the root's place. The drop is saved at once, like a move. The root
  edits act only while a root row is current, and **Remove Root asks first**, saying the files stay
  on disk and how many cached entries go. **Add Root** asks for what the folder lives on — its *storage* — ahead of
  the folder, because a root served by another node will want a different picker below it
  ([[nodes#access-seam]]). When a **root** is current the details pane shows its editors in place of a type line: its **Name** (the
  label, which nothing on disk follows) and its **Storage**: a local folder, a network share, a removable drive or a
  CD or DVD, each with its own glyph. `F5` re-lists the visible columns: a
  folder deleted outside the app disappears, and the selection falls back to its nearest surviving ancestor. A root
  that cannot be listed says so by what it lives on: a **local** folder that is gone is struck through, a share, a
  drive or a disc that is merely away keeps its glyph greyed out, and either way its column holds one row saying
  what is wrong. The model lists off the GUI thread, holds no handle between listings and never uses
  `QFileSystemModel` — the files sub-dock's reasons, plus that browsing must never block a rename
  ([[mounts-and-storage#out-of-band]]). A node is root, folder, file, loading or unreachable, so an offline root is
  a state the model already has ([[mounts-and-storage#offline-mounts]]). Every folder is read through one function
  keyed by root id and relative path, which is what Release 0.4.0 swaps for another node's listing.
- **The Browsers dock** (#396, #379) — a nested dock manager whose every sub-dock is a browser, closable, and the
  first kind is the **table browser**: the generic
  resource browser above as a table over the cache ([[data-model#cache-schema]]), every `.rehu` under the roots and
  every `.tc` no `.rehu` covers. A browser has a name, a filter and a set of visible columns, and several browsers
  exist at once, each with its own filter. The shell is written for more than one kind: the image browser (#403) is a
  second. **Rename and Clone** are on the browser's title bar and its tab's context menu, above QtAds' own *Detach*;
  the `Browsers` menu's *Rename Browser* acts on the current one. Clone asks for a name and starts with the same filter and
  columns. The browser's [x] **deletes** it, without asking — a browser is only a view. **Browsers are the
  agent's, not the catalog's**: each is remembered with where the browsers' sub-docks sit, per catalog on this machine, in a
  file of its own named by the rehuco id (so a moved `.rehuco` keeps them) — never in the `.rehuco`, which
  `rehuco-core` reads and which would carry view state to boxes that have no use for it. They are written when the
  catalog is closed, replaced, or the app quits. A catalog with none remembered opens with one default table browser.
  - **Columns** (#379). Every column the cache can show exists on every view, and the header's context menu lists
    them all, checked where visible — **the only control over columns**: the filter line never names one. The choice
    is kept in the browser's header state with the widths, order and sort, and a clone copies it. A plain browser
    shows authors, title, type, path, publisher, tags, released, size, updated and **format**; the URL and the
    type-specific columns — a tutorial's durations and level, a reference pack's image counts, the fields the cache
    stores that the type's plugin declares ([[data-model#cache-schema]], #399) — start hidden, for a preset to show.
    A header state saved before a column existed shows that column at its default. **A cell holds its value** (a size
    in bytes, a duration in seconds) and a delegate says how it reads, so two sizes that read alike still sort apart;
    the exact size is the cell's tooltip. A missing value sorts as the smallest — first ascending, last descending
    (#466) — so one click on a header brings the rows lacking it to the top. **Format** says which file format a
    resource is in: the `.rehu`'s own version as a number (`0` for an unstamped one), `tc` for a legacy `.tc` — a
    format of its own, not version 0 — and `?` for a `.rehu` whose version the cache does not know (unreadable, or not
    read since the cache began storing it). It sorts by number, with `tc` below them as the oldest format and `?` as
    the missing value.
  - **The current resource** (#379) is the one selected row's, named by its root's id and root-relative path;
    none or several selected name none. Every browser is multi-select.
  - **The filter line** (#398) is GitHub-style: free text plus `field:value` or `field:"quoted value"` tokens
    (`folder`, `authors`, `tags`, `publishers`, `type`), all ANDed; the free text is one phrase matched in a title or
    path, and a repeated field must match both values. It picks the rows **by query, not by proxy**: as the text
    settles (or on Enter) it is compiled to the cache's query and the browser's rows are read again, so the table and
    its status line only ever hold what matches. A read costs about 21 µs per row it returns (#407): the cache's own
    token clauses must be index-driven rather than correlated per row, and what a refresh does with the rows — a status
    total, a sort — must not call back into Qt once per row. Past roughly 30k resources a read belongs on a worker
    thread, with filtering over the rows already loaded, behind the same `CatalogQuery`. **Case:** `authors`, `tags`,
    `publishers`, `type` and a `folder`'s root label fold ASCII only (SQLite's `NOCASE`); the path beneath the root
    folds as the filesystem does (`os.path.normcase`), the rule Roots navigates by — so `folder:lib/FÖLDER` finds
    `Földer` on Windows and not on Linux, where `folder:lib/G03` does not find `g03`. The **status line** totals what
    the model holds, never what a row's `None` hides: the size and the image count each say how many rows they leave
    out, and cover the `.rehu` rows only: a legacy `.tc`'s size and image count are old claims, often a literal `0`,
    so those rows are counted apart (`1,240 resources / 188 legacy .tc / 1.2T (37 unmeasured) / 18,400 images (3
    unmeasured)`). The image total is shown only where a `.rehu` row has a count or is of a type that declares one.
    **The selection** follows it after ` — `: how many rows are selected and their sums by the same rule
    (`CatalogTableModel.totals_of`, one pass over the selected rows, so Ctrl+A costs no call per cell), e.g. `— 3 selected /
    4.1G / 120 images`; nothing selected shows nothing. The line is an elided label: the selection part shortens first,
    then the totals, and the whole line is its tooltip (#462).
    An unknown field is reported on the line, never silently dropped, and the rest of the line still applies. The
    text is the browser's remembered filter; a `columns:` word an earlier build saved in it is dropped as it loads. A
    folder's context menu in Roots — *Show only rehu in this folder* — sets `folder:"<root label>/<relative path>"`
    on the current browser, click-to-filter links set the same tokens on it ([[plugins#filter-urls]]), and an
    **Authors** cell's context menu (#460) offers *Filter by <author>* for each author of its row, read from the
    record rather than split from the cell, or *Clear the filter by <author>* for one the line already names; each
    **replaces** that field's token and keeps the rest of the line. The current browser is the focused one, else the
    one focused last, and a link with no browser open opens a default one to carry it. Roots and the browsers are
    otherwise independent.
  - **New Table Browser** offers presets on its menu (#400) — a click on it is *Default* (the common columns); then
    one *<Type> Columns* entry per type that contributes columns (`catalog_type_fields`), today *Tutorial Columns* and
    *Reference Images Columns*: that type's columns shown, every other type's hidden, a `type:` token on the line, and
    the browser named after the type. A type with no column of its own is not offered. A preset only picks the
    starting header state, filter and name; the browser is then an ordinary one and remembers no preset.
- **A covered file shows its checksum state in the Roots view** (#457). A file's state comes from **its own**
  record only: a same-stem `foo.checksum` beside `foo.rehu`, else the nearest directory-scoped `info.checksum` at or
  above its folder, so a covered subfolder shows states too; an entry an older `info.checksum` still holds for a file
  `foo.rehu` now owns is ignored (#467 moves it). The lister reads the record where it lists the folder, on its
  worker and inside the rename coordinator's hold, and carries it as `DirectoryListing.covered`; the model turns it
  into a `RowChecksum` with `checksum_verdict_for`, so the rows and the Files dock age a result by one rule.
  - **A file reads two ways**: *No checksum* (not listed, listed with no hash, or no record covers it) or a checked
    result, *Matching* or *Not matching*, drawn old when the check has expired or was made at another location. A
    record, a checksum file and a screenshot have no state (*Not applicable*).
  - **The row** shows the state's icon right-aligned in its column, the name eliding before it; a file that did not
    match has its name and icon in red, one whose mismatch is old in orange. **The details pane** shows the icon
    beside a one-line title, and two fixed rows after *Modified* -- **Checksum:** the verdict, **Last check:** the
    date and, in brackets, how long ago -- or *expired*, or *at another location* when that is why it may not count --
    so the block never changes size from one file to the next. A picture
    is the last thing in the pane, below the buttons, so what sits above it stays put.
  - **A verify refreshes the rows in place** through the app's `changed` announcement of the record it rewrote.
  - **A checksum file's default action is *Verify old checksums*** (a double-click, the bold entry): it leaves a check
    that is still valid alone, checks the files whose check has expired and records the ones with no checksum --
    the Checksums dock's *Verify Old*. **Verify checksums** beside it checks every file whatever its last check was.
    A screenshot or a checksum file never offers *Create rehu*: it belongs to a record already, and its associated
    rehu is that record.
  - **Automatically preview the current rehu** (the `Root Catalog` menu and the Root Catalog settings page, one
    setting) lets the Roots view's current row drive the Documents preview. Off, the preview stays where it is; the
    table browsers' selection is not governed by it.
- **A selection shows in the Documents preview** (#381). The browsers and the Roots view get no document sub-docks of
  their own: selecting a resource shows it in the preview dock ([[plugins#dock-shell]]), the one place a selected
  resource is shown, through the one model any Documents dock of the same file holds ([[plugins#view-model]]). **Only a
  different `.rehu` changes it.** No row, several rows, a Roots node with no record, the same resource again, the same
  resource under a new name (a rename re-keys the current row) and a scan's reset of the table all leave the preview
  as it is; a resource open as an ordinary document is focused there instead.
  - **What a selection names.** A browser row names its record by `(root_id, relative)`. A Roots node names what
    opening it would open: a record itself, a folder's `info.rehu`, a file's same-name `.rehu`, the `.tc` of either when
    that is all there is. **A selection never creates a record**: where opening would offer *Create*, nothing is
    shown. `RootCatalog.resource_path` is the one place a key becomes a path, so 0.4.0's re-keying (#414) and
    node-served resources (#421) change that and nothing else.
  - **Which view drives it.** The one the reader is in: the Browsers dock's current browser, or the Root Catalog
    dock, while it is the current outer dock. A selection that moves on its own in a dock the reader is not in does
    not move the preview.
  - **It stays cheap.** A selection is shown once it has stood for 250 ms, like the filter line, so the arrow keys
    load one document per resting row. Showing it does not bring the Documents dock forward — it can be a tab behind
    the dock being selected in — unless the reader closed it.
  - **A double-click is unchanged**: it opens an ordinary document, and when the preview shows that `.rehu` it is
    promoted instead of opened twice.

**The menu bar is the complete index** (#402, #465): `File`, `Root Catalog`, `Browsers`, `View` and `Tools`.
`File` and `Browsers` are twins — the verbs that open or create, the verbs on the open set, then the open list,
A–Z, with the focused one checked; `File` ends with Settings and Quit. `Root Catalog` is the same shape without a list,
there being one catalog: New, Open, Open Recent, then Scan, Add Root and Remove Root, which are the dock's own
actions and so are enabled as the dock enables them. `Browsers` leads with *New Table Browser*; the image
browser (#403) adds its own entry and kind icon when it lands. `View` is what is visible — themes and the dock
toggles — and `Tools` holds the catalog-wide maintenance operations.

Every browser here updates in place when the app moves or changes files — rows and nodes are renamed, moved, inserted
or removed, never reset — by the in-process announcements of [[mounts-and-storage#out-of-band]].

### §13.5.2 Click-to-filter URL convention

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
- **Authors first** (#398). Each author name in the viewer is a `filter://` anchor, beside the external `http(s)` link
  an author entry's URL adds ([[field-schema#authors]]); tags and publishers linkify later. Link handling never
  enables the label's own external-link opening: one handler dispatches on scheme — `filter://` internally,
  validated `http(s)` to the system browser — so a `filter://` link can never leak to the OS, and no other scheme is
  ever followed. A clicked link travels up to the window like a field's status message, and the window brings the
  Root Catalog forward; with no catalog open, its status bar says so.
- **A link is a filter-line token.** Dispatching `filter://authors?name=Foo%20Bar` sets `authors:"Foo Bar"` on the
  current browser's filter line in the Browsers dock ([[plugins#rehuco-dock]]) — one filter grammar, reached by
  typing or by clicking.

## §13.6 Tutorial plugin

[[[plugins#tutorial-plugin]]]

- [#160: feat: LocalEdit5.0 tracer — image lightbox spine (click-to-maximize, ESC)](https://github.com/borco/rehuco/issues/160)
- [#161: feat: LocalEdit5.1 — lightbox navigation (prev/next, hideable strip, live curated set)](https://github.com/borco/rehuco/issues/161)
- [#70: feat: wrapped vs. single-row layout for a document's image strip](https://github.com/borco/rehuco/issues/70)
- [#162: feat: LocalEdit5.2 — folder-rename-from-suggestions renames on disk](https://github.com/borco/rehuco/issues/162)

The tutorial type's four surfaces, composed over the shared field toolkit ([[plugins#field-toolkit]]):

- **Viewer** (triggered by double-clicking `.rehu` in File Explorer), split across two docks
  ([[plugins#viewer-editor-both]]): read-only field display on the **main view**; on the **description view**, a
  horizontal image strip with click-to-maximize, prev/next navigation, hideable thumbnail strip, ESC to
  close, over the rendered Markdown
  description. **Where** a clicked screenshot maximizes is a user preference (the "Images / Display" settings page,
  [[appendices.settings-pages#category-groups]]), not a fixed choice: an overlay over the open document's own client
  area (the default — the surrounding dock chrome, menus, and toolbars stay visible), an overlay over the whole main
  window's client area, or a frameless full-screen window. The strip itself only reports *which* screenshot was
  activated; the document surface owning it decides what opens ([[plugins#field-toolkit]]'s owner-routes-it shape).
  A maximized screenshot opens against the **whole curated set** ([[data-model#image-meanings]]), which it navigates
  in strip order and which **stops at both ends rather than wrapping** — a wrap makes a short set feel endless, and
  the ends are where its shape is legible. Three affordances, all one step: LEFT/RIGHT (with HOME/END for the ends),
  the wheel over the screenshot, and a prev/next glyph that fades in while the pointer is within a band along that
  edge — `min(50 px, an eighth of the viewer)`, so a band never swallows a narrow viewer. **A click steps only inside
  a band**, never on the open screenshot: half the viewer is far too large a target for a step the user did not
  necessarily ask for, and it hid where the affordance actually ended. At the end it would point past, the band is
  hidden outright, so a click there can never step where there is nowhere to step to.
  **The screenshot itself carries no margin** — it fills every pixel the thumbnail row leaves,
  and only the corner controls hold themselves off the edge. That row is the same widget the document's strip is, with
  the current screenshot framed and scrolled into view and a click jumping straight to it. Whether it is showing is
  **per document**, remembered in the document's own saved layout beside which tabs it has open, so one document's
  toggle never decides another's; the settings page holds only the *starting point* a document that has never been told
  otherwise opens with, plus the thumbnail height on each side and how tall the curation editor's preview pane opens
  on a document whose split has never been dragged. Applying any of those four reaches what is **already on screen**
  — open strips resize, open viewers resize and show or hide their row, open editors re-split — so the effect is
  visible where the user is looking rather than promised for next time
  ([[appendices.settings-pages#save-drop-actions]]).
  Neither strip ever paints a scrollbar, and a strip with nothing to show — no screenshots, or every one curated
  away — hides itself rather than leaving an empty band. The document's own strip has a second layout to offer,
  picked in the same settings ("Viewers > Images"): **wrapped**, folding the thumbnails onto as many rows as the
  width needs instead of running them off the right edge, with the strip then as tall as that takes and the
  document's own scrolling reaching the rest. It applies to the strips already on screen like the heights beside
  it. The maximized viewer's row is never wrapped — there it is an index alongside the screenshot, not the content
  itself. The set stays **live**: a curation edit or a scanner swap
  ([[acquisition-tooling#tc-to-rehu]]) re-points an open viewer through the same owner, which keeps the current
  screenshot if it survived, falls back to whatever took its position if it did not, and dismisses the viewer when the
  set empties — a maximized screenshot is never one the strip no longer offers.
  The **curation editor** on the images tab is the write side of the same set: every screenshot as a checkable
  row (checked = in the lightbox) under a sized preview, with buttons — the shared item-list ones, so they look
  and behave like every other list in the app — to move one up, down, to either end, or delete it.
  Because a screenshot's order **is** its numbering
  ([[data-model#image-meanings]]), all of those are renames on disk: they take effect immediately rather than
  waiting for a Save, a delete renumbers everything after the hole it left, and a set arriving numbered from `01`
  is renumbered from `00` the first time it is rearranged. A delete is confirmed first — it is the one edit here
  that cannot be undone. Deliberately single-select: every ordering action names one file. A resource nothing can
  rearrange — one not yet saved anywhere, or a legacy `.tc`, which refuses every screenshot edit as it refuses the
  drop ([[acquisition-tooling#drag-drop-aids]]) — keeps the list and greys the buttons, both row kinds alike.
  A **locked** document ([[data-model#write-integrity]]) goes further and greys the check boxes with them, since
  curating a screenshot writes to a record that may not be written; the rows, their metrics and the preview all
  stay. That is the whole point: a `.tc` is locked, and its images are exactly what the conversion about to run
  is going to act on, so the dock is where that is looked at first. It is the one editor surface a lock leaves
  enabled — every other one is disabled whole, as before.

  **Un-converted pattern-matched images are the dock's second row kind**, listed after the numbered set: an
  image the screenshot name patterns match ([[acquisition-tooling#screenshot-schemes]]) but that a
  conversion has not renamed into the numbered set — left there by a legacy `.tc` not yet converted, or by a rename
  collision a conversion left untouched under its own name ([[acquisition-tooling#tc-to-rehu]],
  [[data-model#image-meanings]]), in natural-sort order. Both row kinds carry the **same enabled checkbox**, moved
  to its own first column so the two align: it is the curation checkbox above (checked = in the lightbox, the
  `hidden_images` list) on either kind, and an un-converted row starts **checked** — shown until the user says
  otherwise, since a picture the patterns recognize is a screenshot whether or not it has a slot yet. The strip and
  the lightbox show every checked row, numbered first, then the un-converted ones (#281). The ordering buttons stay
  **disabled on a pattern-matched row** — it holds no position in the numbered set to move. Two actions are offered
  on such a row, single-select like every other action here: **Convert** takes its own legacy number as its new
  `<stem>NN` when that slot is free, and appends it past the current end of the numbered set otherwise — the
  free-slot-or-append rule of #265 — after which the row re-lists among the numbered set with its checkbox state
  carried across the rename by the same remap the curated-out list already follows; and **Delete**, to the Recycle
  Bin if possible, with a permanent delete confirmed unless *Delete images without asking* is on
  ([[appendices.settings-pages#category-groups]], #291, #312). Moving or deleting renumbers
  files and **never rewrites the description** — an embed pointing at a name that moved or vanished is left exactly
  as the user wrote it — and a one-line hint in the dock says so.

  In a **multi-record directory** ([[data-model#resource-scoping]]) each record's dock shows **everything except
  the *other* stems' `<stem>NN`**: its own numbered set, and every pattern-matched image in the directory, since a
  loose `cover.jpg` carries nothing naming whose it is and either record may claim it with Convert. A delete from
  either dock therefore deletes it for both, and the confirmation says so.

  **On a legacy `.tc` only, a column right after the filename — *After conversion* — says what the whole-directory
  conversion
  ([[acquisition-tooling#tc-to-rehu]]) would do to each pattern-matched row**, read from the same dry-run scan the
  conversion itself runs rather than re-decided here, so the column can never disagree with what Convert then
  does. Every cell is a **filename — the one the file has afterwards**: the `<stem>NN` a row is renamed to, or
  its own name again for a row the scan leaves alone, so the column reads the same way down its length. *Why* a
  file keeps its name is the cell's tooltip, in the scan's own vocabulary and nothing else — its slot is taken by
  an earlier name, by an earlier extension of its own name (the larger one wins), or its own number is at or past
  the highest slot a conversion will write. No image is ever backed up to an `.orig`, so no fourth outcome exists
  here. Hidden on a `.rehu`, where every row already has its name and there is nothing left to convert.
- **Editor**: field editing including the Markdown description; rename from the predefined-candidates list
  ([[data-model#rehu-format]]), which renames on disk. Each scope moves what its own naming convention owns
  ([[data-model#resource-scoping]]): a directory-scoped `info.rehu` renames its **parent directory**, one atomic
  operation carrying everything inside it; a file-scoped `foo.rehu` renames **every file named after it** — the
  record, the `fooNN` screenshots, the `.sfv`/`.md5` manifest, and the content itself, whether that is one `foo.zip`
  or a `foo.001`/`foo.002` multi-part set. Until a `.rehu` carries an explicit manifest of the files it describes
  ([[data-model#resource-scoping]] names that gap), being named after the resource *is* the association, so renaming
  only the record would break the very thing tying the set together. What counts as named after it is decided by a
  **separator**, not a bare prefix: what follows the stem must be nothing, a `.`, or a digit. More letters make a
  different name that merely starts alike, so `foobar.zip` is left to whoever it belongs to. Two further exclusions:
  **directories** (a file-scoped `.rehu` describes files) and anything owned by a **sibling record** whose stem
  extends this one's — with `foo.rehu` and `foo2.rehu` side by side, the digit rule would otherwise sweep `foo2`'s
  whole set into `foo`'s rename.
  A resource whose `.rehu` is **not on disk** is refused outright: a missing record's remedy is a re-read
  ([[data-model#write-integrity]]), and with the record gone there is nothing left to establish what its set was.
  The set is collision-checked whole before the first rename runs and rolled back if one
  of them fails, so a resource is never left split between two names ([[data-model#write-integrity]]) — and the one
  case a rollback cannot fix says so by name. Both scopes rename within a single directory and so are same-filesystem
  by construction; the checksum-gated cross-filesystem move ([[mounts-and-storage#safe-move-rename]]) is a different
  operation, reached from a destination-choosing UI that does not exist.
  A candidate **something already occupies** — another folder for a directory-scoped resource, another `.rehu` for a
  file-scoped one — is offered *disabled, with a trailing `⚿`* rather than as a click that could only fail. A marker
  rather than a color: the disabled palette fights a hue, a colorblind reader may not separate one, and Qt Style Sheets
  cannot inject content anyway (no `content`, no `::before`/`::after` — Qt's pseudo-elements are widget subcontrols),
  so the displayed text is where it has to live. The editor
  holds no path and reads no directory: it asks its owner through a predicate, the same
  field-decides-*that*-never-*what* rule the rest of the toolkit follows. The check is one existence test on the
  resource's own destination, not the whole plan — it is re-asked per keystroke behind a live suggestion list, and
  measured at ~15 µs against ~24 ms for a sibling sweep. It is deliberately **uncached**: a memo table would go stale
  under the app's own rename, under a new document's first save, and under anything done in a file manager while the
  editor sits open, and the OS attribute cache already supplies the speed with invalidation this layer cannot see.
  A rename that fails anyway — a collision on a sibling the cheap check does not cover, or any other refusal — reports
  as an inline banner row on the document, not a modal: the resource is untouched and the candidate list that produced
  the name is still on screen.
- **Follow** (a distinct mode from viewer/editor): sequential playback of the tutorial's files, recording watch progress
  and duration; note-taking (create/view/edit); bookmarking. Progress — per file, a resume position and a *viewed*
  flag — is [[field-schema#watch-progress]]; its sync follows [[sync#overview]]/[[mounts-and-storage#node-handoff]].
- **Web**: search/browse tutorials the user has access to; follow a tutorial from the browser, with the same
  progress/notes/bookmarks behavior as the desktop "follow" mode.

## §13.7 Reference images plugin

[[[plugins#refimages-plugin]]]

Viewer/editor similar in shape to the tutorial plugin (no "follow" mode), with type-specific features. The
four bullets below are the summary; the full treatment — the three data layers and their homes, the scan
sidecar, user-configurable models, what a node needs, and swarm dispatch — is [[reference-images]]:

- **Tagging at two granularities**: archive-level and per-image. Per-image tags are stored as app-managed mutable
  metadata alongside `.rehu`/screenshots (not inside the immutable, checksummed zip), keyed to images by index/filename
  — see [[data-model#image-meanings]] for the screenshot-vs-zip-content distinction and the stale-overlay warning when a
  zip is manually refreshed.
- **Non-destructive redaction**: rectangle/ellipse regions with an effect type (mosaic/blur/solid color/**cover** —
  cover is inpaint-based removal, restoring plausible skin or background rather than occluding; see
  [[reference-images#modes]]), stored as app-managed metadata ([[data-model#image-meanings]]) and applied at render
  time — the original image inside the zip stays byte-identical and covered by the checksum manifest
  ([[data-model#checksums]]). A toggle controls whether redaction is shown; likely a per-user (not just per-device)
  preference, and overridable per document and per image ([[reference-images#redaction-scope]]).
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
its browser/editor contributed by its plugin ([[plugins#browsers]]). All three arrive with the catalog cache (CacheDB's
`.rehudb` — their browsers are what needs it), and none changes the v1 on-disk membership fields
([[field-schema#sources]]), which are already the reference mechanism this design builds on.

| | referenced by | natural home | own wrinkle |
| --- | --- | --- | --- |
| **collection** | member's `collections[]` | members' parent dir *when containment-shaped*, else the configured home | dual placement |
| **author** | credited name in `authors` ([[field-schema#authors]]) | configured home | alias aggregation |
| **learning path** | member's `learning_paths[]` | configured home / owner's per-user state | owned per-user, shared by copy into the reserved `public` scope ([[field-schema#learning-path-ownership]]) |

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
  and the entity's list — each document keeps its single writer, [[data-model#write-integrity]]), never two independent
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
  collection's `info.rehu` sitting in its members' parent directory is only that entity's natural home (the scan
  descends past every record, whatever its type, [[data-model#scan-and-staleness]]). Every other grouping entity lives
  in the **configured creation directory** declared in `.rehuco` ([[mounts-and-storage#rehuco-scope]]). *Discovery* of
  existing entity documents needs no declared locations at all — it is type-based: the scanner finds them wherever
  they sit in any scanned root, so a swarm arriving with its own authors is just documents in its roots.

## §13.10 Shared capability worth extracting

[[[plugins#shared-capability]]]

"Follow tutorial" ([[plugins#tutorial-plugin]]) and the sketch-practice slideshow ([[plugins#refimages-plugin]]) both
want a **timed/sequential presentation** capability, just configured differently (tracked progress + notes/bookmarks vs.
a fixed-duration rotating display + a session log). Worth designing this as one shared core capability that plugins
configure, rather than reimplementing similar sequencing/timer logic independently in two plugins. The practice
side's requirements are in [[reference-images#practice-sessions]].
