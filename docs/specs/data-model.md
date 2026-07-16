# §4. Data Model

[[[data-model]]]

## §4.1 `.rehu` format

[[[data-model#rehu-format]]]

JSON, replacing the YAML `.tc`. The full schema is being designed separately ([[field-schema#overview]], the concrete
v1 field list derived from the `.tc` format) and isn't detailed here, but its scope is settled:

**A `.rehu` is `format_version` plus a map of keyed blocks** — nothing else lives at the top level:

- **The `core` block**, holding the common fields available to every resource type regardless of plugin. The concrete v1
  list is [[field-schema#resource-types]]: `type`, `id`, `sources` (title/publisher/url per platform), `authors`,
  `released` (partial-precision date), `description` (Markdown, can embed local images), the tag lists, the measured
  `original_size`/`current_size` pair ([[field-schema#duration-size]] — empty for a type with no files of its own, e.g.
  Collection), and the `created`/`updated` record timestamps.
- **One block per plugin**, holding that resource type's own fields ([[plugins#plugin-blocks]]), e.g.:
  - *Tutorial*: `duration` (general), `progress` (per user)
  - *Daz3D*: `installed` (per user, per box)
  - *Reference images*: `count` (general), `tag` (general and per-image), `mosaic` (per-image redaction regions)

**Why the common fields are nested rather than top-level** (they were, through format v1): a block has to be
*recognizable*, and while the common fields sat beside the blocks the only way to tell them apart was a **list of every
common field name** — which had to be maintained in lockstep forever, and still could not classify a common field added
by a *newer* build, since an unknown object-valued key is indistinguishable from an uninstalled plugin's block. Nesting
the core replaces that whole list with a single reserved name: **every top-level key except `format_version` and `core`
is a plugin block.** `core` is declared exactly like a plugin ([[plugins#core-vs-plugin]]), which is also what reserves
the name — no plugin may claim it. Unlike a real plugin's block it is never active or inactive
([[plugins#plugin-blocks]]): no document is ever `type: "core"`.

`format_version` stays at the top level because it describes the file's own layout rather than holding fields; a v1 file
is migrated in memory on load and re-stamped the first time it is saved ([[data-model#schema-version]]).

See [[plugins#overview]] for how plugins own their field sets without the core app needing to understand their shape.

A few field-level decisions carried over from the old `.tc` format, worth keeping in mind when the schema is finalized:

- `date` must support partial precision — year only, year+month, or full date — with sensible comparison/sorting across
  mixed precision.
- Fields like publisher/title and learning-path membership must support **multiple values**, not a single scalar — the
  same tutorial can be sold on more than one platform under slightly different names, and can belong to more than one
  learning path.
- A field like the old `online` flag means "is the original source still available," not "is this an online-only
  resource" — worth being careful that the new schema's naming doesn't repeat that ambiguity.
- A field like the old `complete` flag means "are all expected files present," unrelated to viewing/watching status.
- Old single-purpose boolean flags (e.g. `keep`) may eventually fold into general-purpose tags, but that consolidation
  is **deferred** — v1 keeps them as individual booleans, imported 1:1 ([[field-schema#boolean-flags]]).
- Some fields (publisher, title, author, date) are also used to generate candidate folder-name suggestions, which the
  user picks from to rename a resource's directory — a convenience feature carried forward from the old app. With
  multi-valued fields, this needs a notion of a "primary" value per field to build the suggestion from, with others as
  alternates.

## §4.2 Stable identity, independent of location

[[[data-model#stable-identity]]]

Because resources can move between folders, disks, and nodes, **path cannot be the identifier**. Every `.rehu` carries a
UUID minted once at creation time. This UUID identifies the **resource's lineage** — see
[[instances-and-dedup#uuid-is-lineage]] for why this is a
many-to-one relationship (one UUID, potentially many physical instances) rather than "one UUID, one legitimate copy."

## §4.3 Single file, not split metadata/state files

[[[data-model#single-file]]]

Considered splitting `.rehu` into separate metadata vs. per-user-state files to simplify conflict resolution, but
rejected this: it breaks the "one self-sufficient file" property that makes the design work in the first place. Instead,
conflict resolution is scoped to the relevant sub-block *within* the one file ([[sync#overview]]).

## §4.4 Resource scoping: directory-scoped vs. file-scoped

[[[data-model#resource-scoping]]]

Two patterns for what a `.rehu` describes:

- **Directory-scoped**: `info.rehu`, alongside `infoXX.jpg/png/gif/webp` images and an `info.sfv`/`.md5`/`.sha256` checksum
  manifest. Covers tutorials (flat or nested) and folder-based resources generally. The checksum manifest covers
  everything in the directory **except** `info.rehu` and the `infoXX.*` images, so description/images stay freely
  editable without invalidating integrity checks.
- **File-scoped**: `foo.rehu` + `foo00.jpg`, `foo01.jpg`, ... + `foo.sfv`/`foo.md5`, describing a single file like
  `foo.zip`. This needs to extend to **multiple files** treated as one logical resource (e.g. `foo.zip` + `bar.zip`
  together) — naming convention alone can't express that, so the `.rehu` must carry an explicit manifest block listing
  which file(s) it describes.
- **Coexistence**: a directory may end up containing both a directory-scoped `info.rehu` and one or more file-scoped
  `*.rehu` entries (normally this shouldn't happen — it's meant to be one or the other). Rather than forbid this
  outright, the app caches and displays all such entries and flags the situation with a warning, leaving resolution to
  the user.

## §4.5 Checksums

[[[data-model#checksums]]]

- Algorithm in use today: CRC32 (SFV). Subject to change pending benchmarking (CPU-accelerated CRC32 vs. alternatives
  like xxHash or hardware-accelerated SHA). The checksum manifest format should record **which algorithm was used** per
  entry, so a future algorithm switch doesn't invalidate or require migrating existing checksums, and different
  resources can use different algorithms if needed.
- Checksums cover only **immutable original content** — the actual tutorial/resource files — never `.rehu` or the
  `infoXX.*` images, which are designed to be freely editable.
- The Qt app provides UI to generate and verify checksums on demand; each such operation is a task in the task queue
  ([[architecture-design#components]]), and multi-selecting many resources serializes the work rather than running it
  all at once.
- **Execution location is a dispatch decision, not fixed.** A checksum job can run: (a) on the node that owns the files
  (cheapest when the Qt app would otherwise have to pull bytes over the network just to hash them), (b) in the Qt app
  directly against a locally/mount-accessible path (cheapest when that path is faster than going through a node's API,
  or when no node is reachable at all — e.g. an offline checkout on a USB stick), or (c) via a locally mounted path that
  happens to also be served by a node — see [[mounts-and-storage#nodes-serve-mounted]]. The general rule: **prefer
  whichever route gives local-disk-speed access to the actual bytes**; fall back to delegating to the owning node
  otherwise.

## §4.6 Two distinct meanings of "image"

[[[data-model#image-meanings]]]

The design uses "image" for two unrelated things; conflating them caused real ambiguity, so they're separated
explicitly:

- **Screenshots (`infoXX.jpg`/`.png`/`.gif`/`.webp` — the basename-matched, two-digit-numbered siblings of the `.rehu`,
  [[data-model#resource-scoping]])** — app-managed presentation metadata that accompanies a `.rehu`. Editable, **not**
  checksummed, part of the editable record (subject to the online-only-editing rule for resource metadata in v1,
  [[sync#overview]]/[[offline-editing#overview]]). These are what "images" refers to in the viewer's image strip and in
  description embeds.
- **Content images inside a reference-image zip** — part of the **monolithic, immutable, checksummed resource**, exactly
  like a tutorial's video files. The app never edits these. Refreshing such a zip is a deliberate, manual, out-of-band
  action that also requires manually refreshing its checksum; it is not done through this app.

The reference-images plugin's per-image tags and redaction overlays ([[plugins#refimages-plugin]]) describe *content
images inside the zip* but are stored as **app-managed mutable metadata alongside `.rehu`/screenshots**, keyed to images
inside the zip by index/filename — they never modify the immutable zip. Consequence worth handling: if a zip is manually
refreshed (new content, new checksum), per-image overlays may now point at the wrong images. The app should detect the
checksum change and warn that per-image overlays may be stale, rather than silently rendering redactions over the wrong
images.

## §4.7 Scanning strategy and staleness detection

[[[data-model#scan-and-staleness]]]

Scanning is load-bearing ([[architecture-design#why-distributed]], [[mounts-and-storage#out-of-band]]) but the
*strategy* was previously undefined. Two principles:

- **Incremental, version-aware reconciliation is the normal mode; full rescan is a recovery tool.** A node/app should
  detect what actually changed (e.g. by file mtime/size, or by comparing a cheap `resource_version`/timestamp marker)
  and re-read only those `.rehu` files, rather than re-parsing the whole catalog on the hot path. The original
  startup-slowness problem was a full-scan problem; the SQLite cache plus incremental scanning — not raw per-file parse
  speed — is the real lever. (JSON-over-YAML is still chosen for tooling, validation, and benchmarked parse speed, but
  parse speed of a single file is not the primary startup-time factor once the cache exists.)
- **Retained copies record the version they were copied at.** Any locally retained copy of another source's metadata
  ([[mounts-and-storage#durable-retention]]) stores the source's `resource_version`/timestamp at copy time, so staleness
  is a cheap version comparison when the source is reachable again — not a full re-read. This bounds "am I looking at
  stale data?" to a fast check, removing the historical motive for nervous full rebuilds.
- **Verify-on-access closes the out-of-band gap lazily.** The cache records, per resource, the `.rehu` file's own stat
  signature (mtime/size) and a content hash captured at last read — distinct from the [[data-model#checksums]] content
  checksums, which deliberately exclude `.rehu`. Opening, browsing to, or serving a resource re-checks the stat
  signature against the cache (hashing only to confirm a suspected change, off the hot path); a mismatch means the file
  changed out-of-band ([[mounts-and-storage#out-of-band]]), and it is reintegrated on the spot — re-read,
  version-compared, propagated — instead of waiting for a scan. "Just reopen the file" is thus enough to bring an
  out-of-band edit back into the swarm; the incremental scan remains the catch-all for files never touched again.

## §4.8 Per-node local file trio

[[[data-model#local-file-trio]]]

Each node keeps three files of the same basename, sitting together, with sharply different roles and lifecycles:

| File | Holds | Category | Lifecycle |
| --- | --- | --- | --- |
| `.rehuco` | Per-machine config: folder roots, mounts, primary/remote ownership flags ([[mounts-and-storage#folder-add]]), plugin list ([[plugins#overview]]), retention opt-ins ([[mounts-and-storage#durable-retention]]), auth-trusted flag | Local, legitimately *different* per box | Authored locally; never propagated |
| `.rehudb` | The SQLite catalog cache | Derived cache | Rebuildable within the [[architecture-design#why-distributed]] boundary; disposable/regenerable |
| `.rehusw` | Swarm info: membership, users + salted hashes, access rules | Swarm-identical, *propagated* | **Durable, not disposable** — updated by resync, never regenerated from scratch |

`.rehusw` is the concrete on-disk home of the propagated registry that [[discovery-trust-access#membership-model]]–6.9
refer to abstractly. Crucially it is **not** treated like `.rehudb`: a cache rebuild must not wipe it, because a node
that is offline (and may rebuild its cache) must still remember the last-known users/access rules so it isn't blind
until it can resync ([[discovery-trust-access#serve-after-resync]]). It is persisted state that gets *updated*, not
regenerated. Because it carries the user list with salted password hashes ([[discovery-trust-access#user-auth]]), a node
creates it owner-readable only (0600-equivalent).

## §4.9 Write integrity: atomic writes + single-writer-per-managed-file

[[[data-model#write-integrity]]]

- [ ] [#93: feat: lock reasons — named lock causes; unparseable and missing files open locked, empty](https://github.com/borco/rehuco/issues/93)
- [ ] [#94: feat: MessageBanner — inline document notices replace modal error boxes](https://github.com/borco/rehuco/issues/94)

A `.rehu` is the source of truth, and several actors can want to write one (an agent edit, the owning node's metadata
writes, sync reconciliation). Two writers touching one file at once would corrupt it. Two mechanisms compose to prevent
this — and which applies depends on whether the file is **managed** (a node owns its storage,
[[mounts-and-storage#folder-add]]) or **unmanaged** (a loose file no node watches — a fresh export being adjusted, a
single file received from someone; note that local-file mode [[nodes#local-vs-swarm]] can open both kinds):

- **Atomic write is universal — every `.rehu` write, by anyone, is temp-then-rename.** Write to a temp file in the same
  directory, fsync, then atomically rename over the original (POSIX same-FS rename; Windows `ReplaceFile`/`MoveFileEx`).
  A reader never sees a half-written file, and a crash mid-write leaves either the complete old file or the complete new
  file — never a torn one. This prevents *torn* files.
- **Managed files: the owning node is the sole writer — whenever a route to it exists.** An edit to a managed `.rehu`
  that can reach the owning node — from the agent (a node client, [[nodes#two-roles]]), from sync reconciliation, or
  from the node itself — goes *through that node*, which serializes all writes to the file. (Consequently the
  [[mounts-and-storage#out-of-band]] "agent edits through a mount, then notifies the node to re-read" path is **retired
  as the normal editing flow** — the agent asks the node to make the change rather than writing the file the node also
  writes.) When no route exists (local-file mode with no session or no reachable node, [[nodes#local-vs-swarm]]), the
  agent may still write the file directly: that is a tolerated **out-of-band change**, detected and reintegrated via
  [[mounts-and-storage#out-of-band]] (notification, verify-on-access, or scan) rather than prevented. Atomic writes
  bound the residual race to lose-one-never-corrupt, and reintegration is ordered by the **version vector**
  ([[sync#overview]]), not a scalar counter: if the file's embedded vector still matches the node's last-read state, the
  out-of-band edit is a clean fast-forward (the node integrates it and bumps its own component); if the node advanced
  meanwhile, the two vectors are *incomparable* — detected as genuinely concurrent and sent through [[sync#overview]]'s
  merge rules / verdict queue instead of silently colliding.
- **Unmanaged files: the agent writes directly, atomically.** No node exists to route through (local-file mode,
  [[nodes#local-vs-swarm]]), so the agent writes the file itself using the same temp-then-rename discipline. The
  single-instance design ([[nodes#single-instance]]) already prevents two agent windows from contending; atomic write
  makes even a pathological double-write lose-one-rather-than-corrupt.

**Import is the explicit unmanaged → managed hand-off.** A received export (unmanaged, stripped of swarm bookkeeping per
[[discovery-trust-access#cross-swarm-sharing]]) is edited freely in local-file mode (agent writes directly). **Import**
is the discrete act of a node taking ownership — assigning the file to a primary root and minting fresh swarm
bookkeeping (new version vector, instance entry, [[instances-and-dedup#instance-registry]]). Before import, no node
knows the file exists (agent is sole writer); after import, exactly one node owns it (node is sole writer). There is no
window where both believe they own the write, because import is a deliberate, atomic transition. At import the node
treats the file as untrusted outside input — validate it, upgrade its format if older ([[data-model#schema-version]]),
mint new bookkeeping — rather than assuming it is well-formed just because it has a `.rehu` extension. The same
defensive posture applies to *reading* any `.rehu` (a double-clicked file is untrusted input too,
[[nodes#local-vs-swarm]]): parsing enforces sanity caps — total file size, `versions`-list length, entry sizes, JSON
nesting depth — and a file exceeding them opens read-only with a warning (or is refused at import) instead of exhausting
memory or wedging the app.

**A malformed value gets one of three responses, and which one is not a matter of severity.** It follows from two
questions: *is this field ours to interpret*, and *does the file still have a coherent reading*.

| Response | When | Examples |
| --- | --- | --- |
| **Carry verbatim** | The content isn't ours. We don't understand it, so we have no standing to change or drop it. | An inactive plugin block; an unknown key inside the active block; a stray top-level scalar ([[plugins#plugin-blocks]], [[plugins#fallback-editor]]). |
| **Coerce to the default** | Ours, malformed, but what it *means* is not in doubt. | `format_version: "v1"` → `0` (unversioned); a `core` that isn't an object → an empty core; `sources: ["junk"]` → the non-object entry is skipped. A getter must never crash on a value's *type*. |
| **Refuse, with a reason** | The file contradicts the format's own grammar, so there is nothing to fall back *to*. | `format_version` holding an object — it is the file's version, not a plugin block; a `type` naming a reserved key — `core` and `format_version` are not resource types. |

The middle row is the older rule and the wide one: nearly every malformed value has an obvious reading, and reading it
is better than refusing a file over one bad field. The last row is narrow on purpose — reserved for the cases where
*guessing would be a lie*, because the key's meaning in the format is what has been violated. Refusing must name the
offending key and why, since the user's next move (fix the file, or stop trusting its source) depends on knowing which.

Carrying and coercing are not in tension: they apply to different content. The first is about payload this file is
merely custodian of; the second about fields this build owns and can rebuild.

**A coerced reading is safe to display, not to silently save over.** Coercion governs *reading*: it keeps a getter from
crashing and a viewer honest about what the file most plausibly means. But when a field this build owns is **present
and fails coercion** — as opposed to merely absent, which reads as a clean default — letting an edit session write the
coerced default back would quietly replace the malformed-but-possibly-recoverable original. So such a document loads
**locked**: the same read-only lock a newer-than-understood file gets ([[data-model#schema-version]]), with the
offending key(s) named in a persistent, non-modal notice in the viewer (never a dismiss-and-it's-gone dialog — the
lock is state, and its explanation must outlive a click). The remedy is the one refusal would have forced anyway — fix
the file in a text editor, then revert/reopen to drop the lock — without making the file unopenable in exactly the
tool best suited to inspecting it. The `format_version` stamp is the one deliberate exception: repairing a missing or
malformed stamp is a specified deduction ([[data-model#schema-version]]'s repair rule), not a default masking data, so
it never locks on its own.

The same presentation extends to the *refuse* row and beyond it — **every open attempt yields a document view, never a
modal error box.** A file that is refused (the grammar row above), one that cannot be parsed at all (or trips the
read-time sanity caps), and one that is simply *gone* (deleted between sessions) each open as an **empty, locked**
view — never dirty, never savable — whose notice names the failure (for a parse error, including the parser's own
line/column). Fixing the file by hand and reverting retries in place, refreshing the notice with any new failure, so
there is no reopen-and-fail loop. "Missing" stays a distinct cause from "unparseable": bulk-closing the docks of
vanished files must never sweep away a dock whose file the user is mid-repair.

## §4.10 Schema format versioning of `.rehu` itself

[[[data-model#schema-version]]]

The `.rehu` schema will gain fields over time (it is still being designed). Because the offline-media design
([[mounts-and-storage#durable-retention]], [[instances-and-dedup#uuid-is-lineage]]) guarantees old files *will*
resurface years later — off a USB stick, a
sealed DVD, a received export — every `.rehu` must carry its own **format-version field**. Rules:

- **A newer agent/node reads an older file and upgrades it** to the current format on write (the upgrade is itself an
  atomic write, [[data-model#write-integrity]], and for managed files happens through the owning node).
- **An older agent/node encountering a newer file must fail safe, not lossy.** It must not silently drop fields it
  doesn't understand and write the file back — that would quietly delete data. It should refuse to write (read-only
  view), or preserve unknown fields verbatim on round-trip. The cheap robust default: **preserve unknown fields
  untouched** so a round-trip through an older version never loses data.
- **Import is a natural upgrade point** ([[data-model#write-integrity]]): a received older-format file is upgraded as
  the node takes ownership.
- This replaces the historical "rebuild the whole DB on every schema change" habit ([[data-model#scan-and-staleness]]),
  which only existed because the old app lacked both DB migrations *and* file-format versioning. With a format-version
  field plus DB migrations, schema evolution no longer requires a destructive full rescan.
- **Plugin fields are versioned per-block, not under the file-wide version** ([[plugins#plugin-blocks]]): each plugin's
  keyed block carries its own independent format version, so a plugin's schema can evolve without bumping the
  common-field version or any other plugin's. The same upgrade/preserve-unknown rules apply at block granularity.
- **Upgrades happen in memory, on load; the *file* changes only on save.** Opening an old file never rewrites it — the
  upgraded layout reaches disk together with the new version stamp, on the first save, as one atomic write. This also
  keeps the readers simple: only the *current* layout is understood past the load boundary.
- **An upgrade sets the version stamp too — layout and stamp move together, never separately.** A payload whose layout
  and stamp disagree is wrong, not merely un-finalized, and stays wrong for anything that serializes it without going
  through the save path (a node reply, an export). So the load-time upgrade leaves the in-memory document *wholly*
  consistent, and saving is then a plain dump rather than the place the stamp gets fixed up. The same step repairs a
  stamp that was missing or malformed, which is what makes "the version this document reports" trustworthy everywhere
  else — notably for the read-only lock on a newer-than-understood file. **Repairing never lowers**: a newer file keeps
  its own version.
- **Migrations dispatch on the version, resolved once at the load boundary.** Each step declares the version it upgrades
  *from*, so a future migration whose change leaves no detectable shape marker (renaming a field *inside* `core`, say)
  dispatches exactly like one that does.
- **Resolving the version is not the same as reading the stamp.** The stamp is authoritative whenever it is present and
  sane. A **missing or malformed** one is v0 — malformed is not trusted, matching the defensive coercion every other
  field gets, since a `.rehu` is untrusted input ([[data-model#write-integrity]]) — and v0 is the *only* case where the
  payload's shape is consulted, because v0 names no layout to dispatch on. Everything a version stamp is used for
  therefore depends on the stamp being **written where it is known**: whatever builds a payload stamps it, rather than
  leaving a later reader to infer what the writer already knew.

**A foreign format is never a migration.** Two things look alike from a distance — "old shape becomes new
shape" — and must not be merged:

| | **Migration** | **Importer** |
| --- | --- | --- |
| Input | a `.rehu` payload | a *different file format* — `.tc` ([[acquisition-tooling#tc-to-rehu]]), `.dpdml` ([[daz3d-personal-database#import-needs]]) |
| Effects | the in-memory payload, nothing else | writes files, renames siblings, deletes originals |
| Identity | never mints any | mints the UUID and record timestamps ([[data-model#stable-identity]]) |
| Trigger | **automatic**, on every load | **deliberate** — a user action, confirmed |

The trigger follows from the rest: a migration may run unasked precisely *because* it is in-memory,
idempotent and lossless. An importer is none of those, so it must never fire merely because a file was
opened — a `.tc` opens **read-only** and offers conversion instead. The line between them is the same one
that decides what an adapter may fill in: the **encoding**'s version is knowable and free to stamp, while
the *resource*'s identity and timestamps are an import's to mint, once
([[acquisition-tooling#tc-to-rehu]]).

Consequently a `.tc` is *not* "format v0" — it never carried a `.rehu` version to upgrade from, and the
adapter that reads one emits the **current** layout, stamp included.

**File-wide versions so far:**

| Version | Layout |
| --- | --- |
| **0** | **No stamp at all** — a gap, not a layout. Nothing rehuco writes lands here (saving stamps, and the `.tc` mapping stamps what it builds, [[acquisition-tooling#tc-to-rehu]]), so an unstamped file came from outside rehuco or from before stamping existed. Its layout is *inferred*: the v1 flat shape, unless it already carries a `core` block. |
| **1** | Common fields at the top level, beside the plugin blocks. |
| **2** | Common fields nested in the reserved `core` block ([[data-model#rehu-format]]), so a plugin block is recognizable without a list of common field names. |
