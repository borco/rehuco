# §13. Plugins

Resource types (tutorial, reference images, Daz3D, and future types) are implemented as **plugins**, loaded per `.rehuco` declaration (§9.3). The core app provides default plugins for tutorials, reference images, and Daz3D, but the architecture doesn't assume these are exhaustive.

## §13.1 Split between core and plugin-owned responsibility

| Core (same for every resource type) | Plugin-owned (varies per type) |
| --- | --- |
| UUID, instance tracking, checksums, swarm sync | Schema extension — custom fields beyond the common set (§4.1) |
| Tasks/job queue, node communication, REST plumbing | Viewer layout and behavior |
| Permissions/access grants | Editor layout and behavior |
| Dedup detection mechanics | Web rendering and interaction |
| `.rehuco` parsing and plugin loading | Custom actions with their own side effects (e.g. Daz3D install/uninstall) |
| The **field toolkit** (a shared library of reusable field widgets: text, switch, tag-list, date, rating, duration, size, choice, path, image-count, unknown, …) that plugins compose from | Browser columns + cover/shelf rendering for this type (§13.4) |
| The **generic resource browser** (common columns) and the **viewer dock** shell | Search/index contributions (e.g. per-image tag search) |

A resource whose plugin isn't installed/loaded on a given machine should still degrade gracefully — at minimum showing the common fields — rather than failing outright, since `.rehuco` (and therefore plugin availability) is per-machine.

**Plugins span a spectrum from declarative to code.** Two earlier ideas — a code-plugin model, and a TutCatalog5 experiment where `.rehuco` *declared* each type's fields from a fixed toolkit — are unified by layering rather than choosing:

- **Declarative type** — a type defined purely as a *field list* over the shared field toolkit (text/switch/tag/date/rating/…), no code. Cheap to add (config, not programming), safe (zero code execution), but limited to what the toolkit offers. Good for simple types (e.g. a basic "3D object" with title/tags/format).
- **Code plugin** — a type that uses the same toolkit fields *plus* its own custom widgets and actions (the Daz3D install action, refimages redaction overlays, the sketch slideshow). Maximally flexible; the only thing that needs real code.

Both produce the same on-disk block (§13.2) — whether a block's fields came from a declaration or from plugin code is purely a rendering detail. This also answers a trust question (§17.2): **declarative types carry no code-execution risk; only code-plugins are a trust/distribution surface.** "Add a simple new resource type" is a config task; code is needed only for behavior beyond the toolkit.

## §13.2 Plugin blocks: keyed, versioned, single-live-type

> [!NOTE]
> **Implement the block save invariant with Opus, not the auto-switched Sonnet.** The live/inert distinction, and especially the *claim-then-abandon-drops-but-never-claimed-foreign-carries* rule (the worked example below), is the subtle logic most likely to be implemented as the wrong-but-plausible "save the current type" — which silently deletes foreign blocks. Override to `/model opus` for this and check all four steps of the worked example.

Plugin fields are stored in **separate, uniquely-keyed blocks** (e.g. `tutorial:`, `refimages:`, `daz3d:`), one per plugin, each carrying **its own independent format version** (the per-plugin refinement of §4.10 — a plugin can evolve its block's schema without touching the common-field version or any other plugin's). A plugin reads/writes only its own block and never needs to know the shape of another's.

**Exactly one type, exactly one live block.** A `.rehu` declares a single `type`. That type — *not* which plugins happen to be installed — names the one block that is **live** (authoritative, editable by its plugin). Every other block in the file is **inert**, regardless of whether a matching plugin exists: a `refimages:` block inside an `audiopack`-typed file is inert and treated as unknown even when the refimages plugin is installed, because the file's type isn't refimages. Plugin-installed-ness only affects whether the *live* block can be rendered richly or must fall back to the generic editor; it never promotes an inert block to live.

**Block persistence invariant (the rule that governs save):** on save, a block is written **iff**

- it is the **current live type's** block, **or**
- it is **foreign payload that has never been made live during this editing session** (carried verbatim, never silently dropped — a file is a custodian of blocks it doesn't own).

A block that **was made live this session and then abandoned** (the user switched to it, then switched away) is **dropped on save** — by making it live and leaving it, the user asserted "this file is no longer that." All non-live blocks (both kinds) remain **resurrectable from memory until the file is closed**, so switching type back and forth within a session is non-destructive until save.

Worked example (type starts at `audiopack`, file also contains an untouched `refimages` block):

1. Switch to `tutorial`: `audiopack` hidden + kept in memory but **dropped on save** (former live type, abandoned); `refimages` shown as **unknown**, carried (never live). Save writes `tutorial` + `refimages`.
2. Switch back to `audiopack`: in-memory `audiopack` revives; `tutorial` hidden.
3. Switch to `refimages`: refimages becomes **live** — the plugin reconciles it (known sub-fields populate their editors; unknown sub-fields get the migrate/drop UI *within* the refimages area). Save writes **only** `refimages`.
4. Switch away to `tutorial`/`audiopack`: `refimages` is now a former-live-and-abandoned block — no longer shown as unknown, just hidden, and **saving deletes it entirely** (contrast step 1, where the same block key was carried because it had never been live).

The same block key (`refimages`) thus has opposite fates in steps 1 and 4, determined solely by **"was it ever live this session."** Making a block live "claims" it; claiming-then-abandoning discards it; never-claiming carries it.

**Safety net:** because making a block live arms its deletion-on-abandon (a user might switch to a type merely to preview it), a save that drops a previously-foreign claimed block records the discard in the activity log (§7) — "refimages block discarded on date X" — so the *fact* of the drop is traceable even though the values are gone, consistent with the document's "never silently lose reasoning" principle. Optionally the editor may visually distinguish "former-identity, will drop on save" from "foreign, will carry" blocks.

## §13.3 Generic fallback editor for inert / unknown blocks

Inert blocks (and a live block whose plugin isn't installed here) are shown via a generic fallback rather than failing:

- **Unknown block** (whole plugin not the live type, or not installed): a labeled, collapsible section marked with *why* it's flagged — "not the current type" vs. "plugin not installed here" are different situations the user resolves differently. Default is carry-verbatim, with an explicit drop option.
- **Unknown field inside a known live block** (e.g. the installed plugin is an older version than the file's block): per-field UI to **map to a known field, drop, or carry verbatim** — most useful here because the plugin *is* present and the user may know where a stray field belongs. Unmapped, undropped fields are carried untouched.
- Flagged items **stand out in the viewer**, labeled by provenance (newer-version-of-installed-plugin vs. plugin-absent vs. not-the-current-type) so the user knows whether the fix is "upgrade the plugin," "install it," or "this is just inert payload."

## §13.4 Resource browsers (per-type, with shelf/table modes)

The catalog is presented through **browsers**, which are the catalog-level counterpart to the plugin block model (§13.2): just as a `.rehu` has common fields plus a type-specific block, a browser has common columns plus type-specific columns.

- **Generic resource browser** — a table of *all* resources, columns = common fields (title, publisher, url, size, change date). The type-agnostic baseline, and the fallback for any type whose plugin isn't installed (mirroring the generic field-editor fallback, §13.3).
- **Per-type browsers** — extend the generic browser with **plugin-contributed type-specific columns**: tutorials add duration / view-progress; reference-images adds image-count; etc. Contributing browser columns (and cover rendering) is a plugin responsibility (§13.1).
- **Two display modes** — tabular, or **cover/shelf view** (Calibre-style), per browser.
- **Clicking a resource opens its viewer dock** (§5.3).
- **Click-to-filter** (restored from TutCatalog4): tags, author, and publisher render as links in the viewer; clicking one sets the corresponding filter on the active browser (clicking an author shows all that author's resources, etc.). This couples the viewer dock to the browser's filter state — natural under the dockable-UI model — and was the primary filtering affordance in the usable older version.

## §13.5 Tutorial plugin

- **Viewer** (triggered by double-clicking `.rehu` in File Explorer): read-only field display; rendered Markdown description; horizontal image strip with click-to-maximize, prev/next navigation, hideable thumbnail strip, ESC to close.
- **Editor**: field editing including the Markdown description; folder rename from the predefined-candidates list (§4.1).
- **Follow** (a distinct mode from viewer/editor): sequential playback of the tutorial's files, recording watch progress and duration; note-taking (create/view/edit); bookmarking. Progress sync follows §7/§9.6.
- **Web**: search/browse tutorials the user has access to; follow a tutorial from the browser, with the same progress/notes/bookmarks behavior as the desktop "follow" mode.

## §13.6 Reference images plugin

Viewer/editor similar in shape to the tutorial plugin (no "follow" mode), with type-specific features:

- **Tagging at two granularities**: archive-level and per-image. Per-image tags are stored as app-managed mutable metadata alongside `.rehu`/screenshots (not inside the immutable, checksummed zip), keyed to images by index/filename — see §4.6 for the screenshot-vs-zip-content distinction and the stale-overlay warning when a zip is manually refreshed.
- **Non-destructive redaction**: rectangle/ellipse regions with an effect type (mosaic/blur/solid color), stored as app-managed metadata (§4.6) and applied at render time — the original image inside the zip stays byte-identical and covered by the checksum manifest (§4.5). A toggle controls whether redaction is shown; likely a per-user (not just per-device) preference.
- **Search**: tag-based filtering (select from existing tags, e.g. `female`, `back`, `3/4`) is straightforward. Free-text natural-language search (e.g. "3/4 view of male face") is harder and should be scoped as: a cheap fallback (fuzzy match against existing tags/synonyms) now, with a semantic/embedding-based approach as a possible later upgrade — not assumed solved by simple string matching.
- **Sketch-practice slideshow**: timed rotation (e.g. 20 sec/1 min/5 min per image) through a filtered image set, for drawing practice. Records a **session log** (ordered list of images shown, with timestamps/durations) distinct from any lifetime per-image view stats; the user can favorite/tag images from that session afterward, using the same per-image tagging mechanism as elsewhere — not a separate tagging system.
  - **Drawing comparison/critique** (exploratory, not committed): proposed as a two-stage pipeline — (1) deterministic facial/pose **landmark detection** run on both the reference image and the user's drawing, producing measurable deltas (eye height, symmetry, proportions), followed by (2) a cheap LLM call that narrates those numeric deltas in plain language. This is preferred over asking a vision-capable LLM to critique the images directly, which would be less reliably grounded in anything actually measured and more expensive per call. Caveat: landmark detectors are mature for photos but may not generalize well to loose hand-drawn sketches — this needs early prototyping against real sketches before being relied on. Treated as a v2/exploratory enrichment, not a dependency of the core sketch-practice feature.

## §13.7 Daz3D plugin

Viewer/editor similar in shape to the others, plus a **custom action**: install/uninstall the plugin/asset into the user's local Daz3D installation. Tracked per user *and* per box (i.e. "installed on which machine, by whom, when"), since this is a system-integration side effect rather than a view/edit operation — it's the first concrete example motivating "custom actions with tracked side effects" as a first-class plugin capability (§13.1), not just schema/viewer/editor/web.

## §13.8 Shared capability worth extracting

"Follow tutorial" (§13.5) and the sketch-practice slideshow (§13.6) both want a **timed/sequential presentation** capability, just configured differently (tracked progress + notes/bookmarks vs. a fixed-duration rotating display + a session log). Worth designing this as one shared core capability that plugins configure, rather than reimplementing similar sequencing/timer logic independently in two plugins.
