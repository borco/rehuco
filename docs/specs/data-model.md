# §4. Data Model

[[[data-model]]]

## §4.1 `.rehu` format

[[[data-model#rehu-format]]]

JSON, replacing the YAML `.tc`. The full schema is being designed separately ([[field-schema#overview]], the concrete
v1 field list derived from the `.tc` format) and isn't detailed here, but its scope is settled:

**A `.rehu` is `format_version` plus a map of keyed blocks** — nothing else lives at the top level:

- **The `core` block**, holding the common fields available to every resource type regardless of plugin. The concrete v1
  list is [[field-schema#resource-types]]: `type`, `id`, `sources` (title/publisher/url per platform), `authors`,
  `released` (partial-precision date), `description` (Markdown, can embed local images), `hidden_images` (screenshot
  basenames curated out of the lightbox, [[data-model#image-meanings]]), the tag lists, the measured
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

- [#197: feat: enumerate a reference-images resource's content images (.zip/.cbz entries, injected extension set)](https://github.com/borco/rehuco/issues/197)
- [#222: feat: Plugin > Reference Images settings page — configurable content-image extension list](https://github.com/borco/rehuco/issues/222)
- [#198: feat: compute the content-image count — advertised_count / current_count with a measure/apply
  row](https://github.com/borco/rehuco/issues/198)
- [#250: fix: info.tc is a directory-scoped resource](https://github.com/borco/rehuco/issues/250)
- [#254: feat: a record counts only what it covers](https://github.com/borco/rehuco/issues/254)

Two patterns for what a `.rehu` describes:

- **Directory-scoped**: `info.rehu` — or the legacy `info.tc` a conversion has not reached yet, which tc4 wrote one
  of per resource directory and which is therefore directory-scoped in exactly the same sense (#250) — alongside
  `infoXX.jpg/png/gif/webp` images and an `info.checksum` record
  ([[data-model#checksums]]). Covers tutorials (flat or nested) and folder-based resources generally. The record covers
  everything in the directory **except** `info.rehu` and the `infoXX.*` images, so description/images stay freely
  editable without invalidating integrity checks.
- **File-scoped**: `foo.rehu` + `foo00.jpg`, `foo01.jpg`, ... + `foo.checksum`, describing a single file like
  `foo.zip`. Whether this must extend to **multiple files** treated as one logical resource via an explicit manifest
  block in the `.rehu` is a Daz3D-milestone question ([[daz3d-personal-database#multi-part]]), and its only remaining
  caller: reference-images resources are decided *not* to need it (#197, below), and DAZ multi-part archives share a
  stem and differ by index — a shape a naming convention may already express, unlike the `foo.zip` + `bar.zip` example
  this block was originally justified by.
- **Coexistence**: a directory may end up containing both a directory-scoped `info.rehu` and one or more file-scoped
  `*.rehu` entries (normally this shouldn't happen — it's meant to be one or the other). Rather than forbid this
  outright, the app caches and displays all such entries and flags the situation with a warning, leaving resolution to
  the user.
- **The rule is stated once and every layer reads it** (#250). *Which* filenames mean *this record describes its
  directory* is one predicate — `is_directory_scoped` — asked by the content walk, the content-image walk, the rename
  plan, every job label and the agent's tab title. It used to be spelled out at each of those eight places, all of them
  agreeing on `info.rehu` and all of them blind to `info.tc`: a catalog opened before conversion got five tabs titled
  `info.tc` and a `Verify checksums` that hashed the `.tc` file rather than the resource it describes, writing an
  `info.checksum` whose baseline was one small YAML file. A named `foo.tc` behaves as `foo.rehu` does, unchanged —
  the rule is about the one filename, not the extension.
- **A record counts only what it covers** (#254). Coverage is decided by **the records present**, never by what is on
  disk, and it is exclusive: a subdirectory holding an `info.rehu`/`info.tc` is out of every ancestor's content
  **wholesale** — files, subtree and all — because that record covers its own directory; a file-scoped `foo.rehu` takes
  its same-stem siblings out of the enclosing record's content, because those siblings are the whole of what it
  describes; and whatever no record claims belongs to the nearest enclosing directory-scoped record, at any depth.
  This reverses the overlap the rest of this document used to record as accepted, on one argument: **summing every
  record's measured size has to answer a library's**, which is the aggregation the catalog cache exists to do
  ([[data-model#scan-and-staleness]]), and under an overlap it cannot — a nested resource was counted once for itself
  and again for each of its ancestors. Everything downstream of the walk follows: sizes, content-image counts and
  checksums alike, since they are all one enumeration (#226). The stem is compared **whole**, so `foo.part2.zip` is
  not `foo.rehu`'s.
- **A legacy document keeps its checksum actions.** Verifying an unconverted resource against the `.sfv` a predecessor
  left beside it is the case #243 exists for, and the record it seeds is the one the converted resource inherits.
  Refusing the actions while a document is locked would have been the cheaper fix and throws that away.

What a **reference-images** resource's content *is* was settled by #197: content lives inside archives — `.zip` or
`.cbz`, a comic-book zip being the same container under another name — never as loose image files beside the `.rehu`.

- File-scoped `foo.rehu` → the single same-stem archive (`foo.zip`/`foo.cbz`) **and nothing else**. Siblings in the
  same directory belong to other resources or to none, and are never opened — a whitelist of one, not a directory walk
  with filters.
- Directory-scoped `info.rehu` of type `reference_images` → every archive under its directory **that no other record
  covers**, root and
  subdirectories, recursively. A nested `info.rehu` **is** a boundary (#254): a subdirectory carrying its own document
  is another resource, handled per its own type, and its archives are counted there rather than here — as is an archive
  sitting beside a same-stem `foo.rehu` of its own. The overlap this used to accept is resolved by the coverage rule
  above, for the reason it gives.
- **Not** a curated list of member archives — a reference-images resource is one file or one directory; the manifest
  block contemplated above is not needed here.
- **Which archive entries count as images is the user's to set** — the enumeration takes the recognized extension set
  as a parameter, and the `Plugins > Images` settings page (#222) supplies it — one editable list, one
  format per entry, starting from `jpg, jpeg, png, webp, avif` and resolving back to that shipped set whenever it names
  nothing ([[appendices.settings-pages#category-groups]]). A pack in a format the shipped set
  omits (`.bmp`, `.tif`, `.tga`, `.psd`) is a preference change, not a rebuild.
- **Counting them fills `current_count`, and only when asked** (#198) — the editor shows the measured count beside
  the stored one and stores it on an explicit apply, never on open. The two disagreeing is *information*: the archive
  was refreshed behind the app's back ([[data-model#image-meanings]]), which an automatic fill would erase before
  anyone saw it. What the pack itself claims lives separately, in `advertised_count` ([[field-schema#field-types]]).

## §4.5 Checksums

[[[data-model#checksums]]]

- [#226: feat: excluded-files settings page — one pattern list shared by the size scan and checksums](https://github.com/borco/rehuco/issues/226)
- [#203: feat: the .checksum record — per-file hash, verification date and status, generate and verify](https://github.com/borco/rehuco/issues/203)
- [#241: feat: rename-aware jobs — a rename never waits for a scan, and a job follows the resource it moved](https://github.com/borco/rehuco/issues/241)
- [#204: feat: checksum actions — generate/verify from the app as task-queue jobs](https://github.com/borco/rehuco/issues/204)
- [#245: bug: an unreachable resource reads as an empty one — a clean verify, and a generate that drops entries](https://github.com/borco/rehuco/issues/245)
- [#242: feat: periodic checksum sweep — verify a catalog recursively, skipping what was checked recently](https://github.com/borco/rehuco/issues/242)
- [#243: feat: seed a .checksum from a legacy .sfv/.md5/.sha\* manifest on first verify](https://github.com/borco/rehuco/issues/243)
- [#244: feat: checksum viewer dock — per-file status and date, with verify/generate actions](https://github.com/borco/rehuco/issues/244)
- [#254: feat: a record counts only what it covers](https://github.com/borco/rehuco/issues/254)
- [#257: feat: a pruned claim moves to the record that now covers it](https://github.com/borco/rehuco/issues/257)
- [#256: feat: import options — convert the .sfv, and optionally verify](https://github.com/borco/rehuco/issues/256)
- [#259: fix: a legacy manifest is never retired once its claim is in the record](https://github.com/borco/rehuco/issues/259)

- **The algorithm was measured rather than inherited** (#203). This section used to say the choice was *"subject to
  change pending benchmarking"* and named nobody to run it — the only benchmarking job the specs describe
  ([[mounts-and-storage#node-benchmark]]) grades a *node's* cold-read throughput for dispatch and never compares
  algorithms. `test_checksum_algorithms_benchmark` is that comparison, kept in the repository and re-runnable with
  `make checksum-bench`: it folds one fixed 64 MiB in-memory block through each candidate, because the read loop moves
  the same bytes whichever digest consumes them, so I/O is a constant and only the fold is the variable.

  Median of 15 rounds, AMD Ryzen 5 5600, Python 3.14.6, 2026-08-04:

  | algorithm | ms / 64 MiB | throughput |
  | --- | --- | --- |
  | **XXH3-64** | **2.94** | **22.9 GB/s** |
  | CRC-32 | 7.14 | 9.4 GB/s |
  | BLAKE3 | 14.40 | 4.7 GB/s (measured, not shipped) |
  | SHA-1 | 29.41 | 2.3 GB/s (measured, not shipped) |
  | SHA-256 | 31.48 | 2.1 GB/s |
  | SHA-512 | 68.6 | 0.98 GB/s (SHA-384 measures the same; not shipped) |
  | MD5 | 70.52 | 0.95 GB/s |

  **XXH3 is the default.** Nothing outside this app reads a checksum record, so there is no interop to trade the speed
  against; CRC-32 stays available because that is what the existing catalog's `.sfv` files hold. MD5 losing to SHA-512
  is not a mistake in the table: SHA-2 has hardware acceleration on this CPU and MD5 has none. Every candidate is far
  above any disk this reads from, so a sweep is I/O-bound whichever is chosen — what the choice buys is headroom for
  the day the storage is not the bottleneck.

  **Five ship, and only five**: XXH3 for what is written, and CRC-32, MD5, SHA-256 and SHA-512 because those are the
  spellings a legacy manifest is realistically written in, so an entry seeded from one (#243) stays checkable. SHA-1,
  SHA-224 and SHA-384 were **dropped from the shipped set** — nothing writes them, they are not what the legacy
  catalog's manifests hold, and every offered algorithm is a row in a radio group about a question most users never
  ask. Naming an algorithm
  costs a line; *offering* it costs the reader's attention, and a longer list makes the one that matters harder to
  find. Dropping one is safe because the record already answers for it: an entry whose hash sits under a key this
  build has no algorithm for is **`malformed`** — reported, and carried through byte-for-byte. It is never re-hashed
  under the current algorithm, which would replace a claim that was never checked with one that trivially passes.
  That is the same rule as *a new hash is only ever kept for a matched file*, reached from the other direction.

  **`gxhash` was measured and rejected** (0.7.0, MIT). At **23.3 GB/s (64-bit) / 28.9 GB/s (128-bit)** one-shot it is
  the fastest thing tested, and it is unusable here: upstream states plainly that *"GxHash is not an incremental
  hasher, and all inputs provided to the `update` method will be accumulated internally"*. Through the chunked read
  loop this app actually uses it measures **0.09 GB/s** — 100× slower than CRC-32 — while buffering the whole input,
  which for an 8 GB video means an 8 GB resident buffer. A hash that must see the file in one piece cannot hash the
  files this catalog holds.

- **The read chunk is 1 MiB**, from the same benchmark's 64 KiB–16 MiB sweep: below 256 KiB the per-`update` call is
  visible on the cheapest fold (CRC-32 costs 4% more at 64 KiB), above it nothing changes but the resident buffer.
  It is also the granularity at which a running job releases a file handle, so a rename never waits longer than one
  chunk read (#241).

- **Every algorithm ships; the set is closed.** `xxhash` (BSD-2-Clause) is a dependency, and the SHA-2 family and MD5
  come from `hashlib` — so an algorithm is added by editing one file, never by dropping a package into an install, and
  there is no optional-backend path to reason about. **BLAKE3 was dropped**: it existed to be written in `b3sum`'s
  format for an external checker to verify, that interop is gone, and it folds a third of XXH3's throughput. What a
  record written by some *other* build names, and this one has no entry for, is a question for whoever reads the
  record — it is not answered by keeping an entry that cannot hash anything.

- **A `.checksum` is a record of verification over time, not a manifest** (#203) — per content file: which hash, when
  it was last checked, and what the answer was. That is what lets a sweep skip what was checked recently (#242), and
  it is not expressible in any format an external checker reads, so `cfv` interop is dropped deliberately. It is JSON,
  sits beside the `.rehu` under the same stem (`info.rehu` → `info.checksum`), and carries its own `version` for the
  migration chain to climb:

  ```json
  {
    "version": 1,
    "files": [
      { "name": "foo1/bar1.zip", "crc32": "42342424",
        "verified": "2026-08-04T23:34:56Z", "status": "matched" },
      { "name": "bar2.zip", "status": "unexpected" },
      { "name": "foo3/bar3.zip", "xxh3": "42342424",
        "verified": "2026-08-04T23:34:56Z", "status": "mismatched" }
    ]
  }
  ```

  `name` is relative to the `.rehu`, POSIX-separated, never absolute and never escaping the directory. **The hash key
  is the algorithm tag**, at most one per entry and present only once hashed — which is how *record which algorithm was
  used per entry* is satisfied literally, and it is genuinely per entry, so `crc32` and `xxh3` entries sit side by side
  and changing the configured algorithm invalidates nothing. `status` is `matched` / `mismatched` / `missing` /
  `unexpected` / `malformed`; a `malformed` entry is one the reading build cannot read, and it costs itself while its
  neighbours still verify.

- **Generate and verify take the same selection**, because they are two halves of one workflow and a selection meaning
  different things in each would be a trap: which files (one, a set, or everything), and a staleness window whose
  *absence* is how force is expressed — no separate force flag to drift out of step. **A targeted generate re-baselines
  exactly the named entries and carries every other byte-for-byte**, which is what makes the real loop work: verify,
  inspect what came back `mismatched`, decide whether the change was genuine (an archive legitimately repacked; or
  corruption with no backup, where keeping a checksum that can only ever fail helps nobody), then re-baseline just
  those files without re-reading the terabyte that was fine.

- **Migration happens in one pass, and never launders corruption** — with *Update checksums on verify* on, an entry
  recorded under a non-default algorithm is read **once** and fed to two digests at the same time, its own and the
  default. The *recorded* algorithm decides the verdict: if it matches, the old key is dropped and the new replaces it;
  if it fails, the entry is `mismatched`, keeps its old key, and the new hash is discarded. Blessing bad bytes under a
  new name would produce a record that then looks clean forever.

- **A sweep adopts** a content file with no recorded hash — hash it, date it, record it `matched` — so `unexpected` is
  a report state rather than a resting one.

- **A resource checksummed before this app existed is verified, not baselined** (#243). The catalog carries `.sfv`
  files written by tutcatalog4 and by external checkers, with `.md5`/`.sha*` here and there. Those suffixes were
  already recognized as bookkeeping so they never count as content, and nothing writes one — but nothing *read* one
  either, so a resource checksummed for years read to this app as a resource with no checksums, and its first verify
  would have recorded today's bytes as `matched` about bytes nobody ever compared. The old file is a **claim, made
  when the files were known good**, and it can still be checked today. A verify that finds no `.checksum` and does
  find a **same-stem** manifest beside it — `info.sfv` next to `info.rehu` — seeds its entries from that file and
  behaves as a verify against them, writing the `.checksum` once at the end. Six decisions carry it:
  - **Seeding produces entries, not a second kind of run.** Each line becomes `{name, <algorithm>: <digest>}` with no
    date and no status, which is a shape verify already knows: present files are hashed and compared under the
    algorithm the *suffix* named, an absent one is `missing` and **keeps its recorded hash** so the claim survives the
    file's return, and content the manifest never listed is adopted exactly as any unlisted file is. `only`, the
    staleness window, the progress denominator and the migration therefore compose for free — a seeded `crc32` entry
    read with *Update checksums on verify* on is checked as `crc32` and re-recorded as XXH3 from the same single read,
    and the corruption rule is unchanged.
  - **Seeding is finding a record, not creating one**, so it happens with *Create missing checksum on verify* off.
    That setting means *start from an empty record when there is nothing at all to start from*, and a resource with a
    `.sfv` has something. A manifest that yields no usable entry yields no record either, and the run refuses as it
    would have before — the setting's meaning is untouched.
  - **Only content is seeded, and *not there* is not the same as *excluded*.** A name that resolves to a file today's
    enumeration leaves out — a screenshot, a `Thumbs.db`, another record's bookkeeping — is dropped, because a
    predecessor was free to checksum files this app deliberately does not, and carrying such an entry would make every
    screenshot edit a permanent `mismatched` in a record that can never come clean. A name with nothing there at all
    is the opposite case and is kept: it is the claim about a file that has gone.
  - **One manifest is read, by a fixed suffix precedence** — `sha512`, `sha384`, `sha256`, `sha224`, `sha1`, `md5`,
    `sfv` — and the others beside it are reported ignored. Merging several is not worth the ambiguity about which one
    wins per file, and a silent pick would be worse than a stated one. A suffix naming an algorithm the shipped five
    omit is passed over rather than chosen and then failed, so a readable `.md5` is not shadowed by a `.sha1`.
  - **A line this build cannot read costs itself** — reported, and the rest of the file still seeds — the same rule a
    malformed record entry is under. Names are normalized to POSIX `/` (these files mix separators freely) and must
    land *inside* the resource; an absolute name, a drive letter or an escaping `..` is dropped and never resolved.
    Encoding is UTF-8 falling back to cp1252, since a non-ASCII filename in a file a Windows tool wrote years ago is
    a cp1252 byte sequence rather than invalid UTF-8 to give up on.
  - **A manifest is retired once its claim is absorbed** (#259) — the run that wrote the record renames `info.sfv` to
    `info.sfv.orig`, and every weaker same-stem manifest the precedence passed over with it. The sixth decision, and
    the one this section shipped without: it was made in the seeding module's docstring rather than here, so the design
    went out with the question unasked. Leaving the file is not the harmless no-op it reads as. Nothing consults it
    while the record is there, so it surfaces nowhere and looks inert — and it becomes the authority again the moment
    the record is lost or deleted, at which point a verify re-seeds from it and reports `mismatched` for every file
    legitimately changed since; after *Update checksums on verify* has re-keyed the matched entries the two cannot even
    be reconciled to detect that one supersedes the other. **Renamed, not deleted**: `.orig` is the conversion's own
    backup suffix ([[acquisition-tooling#convert-mechanics]]), so a retired manifest joins the resource's backup set
    for Revert and Discard with no new vocabulary, and the content walk already skips it. No marker is needed and none
    is written — the run that absorbed the claim is the one retiring it, which is also the moment *unrepeatable if the
    record is lost* is at its weakest, the record having been written atomically from that very file a moment earlier.
    A manifest naming an algorithm the shipped five omit is **not** retired: nothing read it and nothing considered it,
    and a build that ships that algorithm can still use it.

  It is **one-way and it happens once**: from then on there is a `.checksum`, so the next verify reads that and the
  legacy file is never consulted again — and it is renamed aside, by the decision above, so that stops being a promise
  about what nobody reads and becomes a fact about what is there. **It is never deleted**, only retired: it stays
  out of the content set either way, and deleting it would make the step unrepeatable if the new record were lost —
  which retiring, being one rename away from undone, does not.
  Normalization lives in the conversion, which is the seam that knows the file came from a Windows tool; the record
  reader stays strict and is **not** taught to normalize, since a reader that did would make one `.checksum` mean
  different things to a Windows agent and a Linux node.

- **Seeding is also an operation of its own, and it hashes nothing** (#256). The step above happens *on the way past*
  a verify, which then reads every file — fine for one resource a person is looking at, useless for a catalog-wide
  migration, which would have to read the whole library to carry claims it has not been asked to check. So a
  **seed-only** call writes the record from the manifest and stops. It is what a bulk import runs, once per converted
  resource, and it is **not optional**: there is no version of *converted* that leaves a years-old claim behind as a
  file nothing reads. Two things make it safe to stop there. The entries land **dateless**, and a dateless entry is
  never fresh whatever the staleness window, so the next sweep checks every one of them with no force asked for and
  nobody tracking which resources were done — a converted-but-unread catalog is **self-healing** rather than a state
  to remember. And a resource that already has a `.checksum` is **left alone**, the same one-way rule: the record is
  what supersedes the manifest, and re-seeding over it would replace dated verdicts with an old claim. An unreachable
  resource refuses (#245) rather than seeding a record whose every line would read as a claim about a file that has
  gone. Where a record *is* already there and a manifest is still beside it, the remediation below applies instead.

- **A record written before its manifest was absorbed is remediated, not left** (#259). What retirement leaves is a
  clean rule going forward and a catalog that predates it — resources hand-converted into `.rehu` + `.sfv` +
  `.checksum`, where nothing in the files says whether the record came from that manifest or was baselined
  independently of it. The answer is a re-seed that **merges** rather than overwrites:

  | record entry | named by the manifest, not excluded | outcome |
  | --- | --- | --- |
  | any | **yes** | digest replaced with the legacy claim, `verified` **cleared** |
  | any | no | **untouched** — digest and date kept |

  So a file added after the manifest was written keeps its baseline and its timestamp, and a `missing` entry the
  manifest never mentioned keeps its claim about a file that has gone; only what the manifest is actually
  authoritative about is reset, and it is re-checked, honestly, on the next verify. A name the manifest carries that
  the record has never held becomes an entry, since it is a claim held nowhere else. The exclusion half is
  **inherited, not built** — a line naming something the enumeration leaves out never becomes an entry at all, so it
  can clear nothing — and the manifest is retired afterwards, as above. This is remediation and is **allowed to be
  narrow**: the seeding path no longer produces the state, and the one door it recurs through — a revert restores a
  retired manifest wholesale, beside the record it deliberately keeps ([[acquisition-tooling#convert-mechanics]]) —
  heals on reconversion, since a conversion merges and retires whether or not a record is present. So the merge takes
  no options and generalizes to nothing.
  The bulk import is where it is offered, since that is where a legacy catalog is already being walked
  ([[acquisition-tooling#tc-to-rehu]]).

- **A verify has three modes, not two, and the fourth is refused** (#256). Two independent choices — may this run
  *create* a record, and may it *seed* one — make four combinations, and one of them is incoherent:

  | create | seed | |
  | --- | --- | --- |
  | off | on | the ordinary verify — seed from a manifest, else refuse (#243) |
  | off | **off** | **check what is recorded** — refuse where nothing is |
  | on | on | the sweep with *Create missing checksum on verify* (#242) |
  | on | off | **refused** |

  The middle one is what a run queued *behind* a seed asks for: the claim is already in the record, and seeding again
  would spend the resource's one seed on a file that has been read. It also dissolves an ordering question rather than
  answering it — a check that somehow runs before its record exists costs a `stat`, refuses with a sentence, and Retry
  is the recovery, so nothing has to arrange the two. The last combination would adopt every file on disk as a fresh
  baseline while a perfectly good manifest sat beside it unread, which is precisely the throwing away of an old claim
  seeding exists to prevent; a **generate** says that honestly and is what a caller who means it should ask for.

- Checksums cover only **immutable original content** — the actual tutorial/resource files — never `.rehu` or the
  `infoXX.*` images, which are designed to be freely editable.
- **What a resource's content *is* is computed once and shared** (#226) — `rehuco_core.rehu_content_files` resolves it
  from the `.rehu` path, and both the size-on-disk scan and checksum generate/verify read that one answer. A file
  summed by one and skipped by the other is a bug with no honest resolution: a verify would report an
  *unexpected new file* the size the user was shown already counted.
- **Two tiers of exclusion, and only one is the user's.** **Structural** — **every record** a scan meets, at any
  depth, together with the files that belong to it: its `<record>NN` screenshots (`<record>NN` plus an image
  extension, the same shape [[data-model#image-meanings]] defines, so a numbered *video* stays content) and its
  `<record>.checksum` record -- and the legacy manifest suffixes a predecessor or an external checker may have left
  beside it. Not only the scanning resource's own — a nested `bar/info.rehu` and a
  file-scoped `baz.rehu` in the tree bring their own bookkeeping, and all of it is skipped. **Find the records
  first, drop what each one claims, and count what is left** — with two conditions that fall out of that order.
  A record claims **only its own directory**, since screenshots and a manifest are its siblings: a root
  `info.rehu` does not reach down and claim a `bar/info00.jpg` that has no `bar/info.rehu`, while a
  `baz/info00.jpg` beside `baz/info.rehu` is skipped. And **the record has to exist** — a name is bookkeeping
  because a record claims it, never because of its shape, so `xxx00.jpg` with no `xxx.rehu` and `yyy.sfv` with no
  `yyy.rehu` are ordinary files that merely look like bookkeeping. **A record is a `.rehu` or a legacy `.tc`**
  (#250) — so an unconverted `info.tc` is its directory's bookkeeping and claims the `info.sfv`, `info.checksum` and
  `infoNN` siblings beside it, exactly as the `info.rehu` replacing it will. Otherwise the same directory measures a
  different set the moment it is converted, for a reason that has nothing to do with its content, and a claim seeded
  from the old manifest (#243) would describe a resource that no longer exists. **A legacy record claims its
  screenshots by scheme rather than by stem** — `01.jpg`, `cover.jpg`, `sample-01.jpg`, `file(2).jpg`, `file-01.jpg`
  ([[acquisition-tooling#screenshot-schemes]]), none of them named after the record, so the `<record>NN` rule cannot
  reach them and only a `.tc` in the same directory says whose they are. What is skipped is exactly what a conversion
  renames aside, winners and losing variants alike; where no `.tc` sits, a `01.jpg` is an ordinary file and stays
  counted.
  **A retained `.orig` conversion backup is
  structural as well** (#253), and is the one exception to that last condition: a backup belongs to the directory it
  sits in rather than to a stem — a legacy screenshot is named `cover.jpg`, carrying nothing that ties it to its
  resource ([[acquisition-tooling#convert-mechanics]]) — so there is no record to look it up against, and **any**
  `.orig` counts. That definition is asked of the backups module rather than restated here, which is what keeps the
  set a walk skips identical to the set a revert would restore. A bulk import retains every backup by default, so
  counting them would bake each converted resource's own `info.tc.orig` into its first checksum baseline, and
  discarding the backups afterwards — the encouraged cleanup — would then report a missing file for every resource in
  the catalog. It is deliberately not
  editable, and the reason is mutability rather than ownership: a record, its screenshots and its manifest can
  change at any moment, so a size or a manifest that counted them would need recomputing every time anyone edited a
  description or added a screenshot. Excluding them is what lets a measurement stay valid until the *content*
  changes. A nested record's real content leaves too, but under the coverage rule rather than this one (#254): the
  subdirectory holding it is out wholesale, and a file-scoped record's same-stem siblings are its own
  ([[data-model#resource-scoping]]). **Junk** — `Thumbs.db`,
  `ehthumbs.db`, `desktop.ini`, `.DS_Store`, `._*` by default — is the tier the `Excluded Files` settings page
  (#226) edits, as filename globs matched case-insensitively. `Thumbs.db` earns its place because Windows still
  writes per-folder thumbnail caches on network shares ([[packaging-deployment#ts230-as-nas]]), and `._*` is the
  macOS AppleDouble residue that appears for the same reason; neither is content, and both change a size and a
  checksum without anyone touching the resource.
- **The junk list falls back to the shipped defaults when it names nothing** — empty, absent or unreadable. Falling
  back to *no exclusions* instead would silently start counting every share's `Thumbs.db`, which is the churn the
  list exists to prevent.
- **Exclusions govern the directory-scoped case only.** A file-scoped `foo.rehu`'s content is its same-stem siblings
  — a whitelist named by the `.rehu` itself ([[data-model#resource-scoping]]) — so a neighboring `info.rehu`,
  `bar00.jpg` or `bar.zip` is out of scope *before* any pattern is consulted, and emptying the list cannot change
  that.
- **The record does not store the list it was generated under, and it does not need to** (#203, answering this
  section's own open question). Verify checks *what the record lists*: every file with a recorded checksum is hashed
  and compared, so matched / mismatched / missing are decided without consulting the setting at all. The exclusion
  list decides what gets hashed at **generate** time, and at verify time it shapes one thing — the list of content
  files the record does not cover, which is advisory and never makes a resource dirty. So a changed junk list can move
  a file in and out of that advisory list and can never turn a match into a mismatch. Storing it would buy an
  exactness nothing needs, at the cost of a record that disagrees with the setting the user is looking at.
- **An unreachable resource is neither an empty one nor a resource without checksums** (#245). The walk
  reports the directories that would not list rather than answering *nothing found*, because the two
  readings had become one: a verify over an away mount reported a clean run against a record it had
  invented, and a full generate over a partly-offline tree **deleted** the hashes for the branch it could
  not see. Three answers fall out of one enumeration, and they differ because the callers do:
  - **A run over a resource whose own directory will not list refuses**, before it looks for a record —
    *the mount is away* outranks *this resource has no checksums*, and a job (#204) can then say the
    first rather than the second.
  - **A full generate may drop an entry only where the walk was complete.** Dropping what a walk did not
    find is safe exactly when the walk could see, so entries under an unreadable branch are carried
    untouched and reported. A verify was never exposed: it checks what the record lists rather than what
    a walk finds, which is the property that saved it.
  - **A measurement over the whole resource refuses rather than reporting low.** A size or a duration
    summed over the branches that happened to answer is not this resource's, and a number that reads as
    authority is worse than no number — the same rule as *a backend that cannot run reports that rather
    than measuring `0`* ([[field-schema#duration-size]]), one step earlier in the same walk.
- **A verify drops the entries the coverage rule says were never content** (#254), and says how many and why. A verify
  otherwise only ever *adds*, so a record written before *a record counts only what it covers* would carry its
  resource's own `info.tc.orig` backups, a `Thumbs.db` a Windows browse dropped in, and a nested record's bookkeeping
  forever — every one of them adopted, hashed and dated by an earlier run. Four decisions:
  - **What goes is decided by the name, never by absence.** The enumeration is a disk walk, so *deleted* and *excluded*
    look identical to it; an entry is dropped for what it **is**, which is why a file that is merely gone keeps its
    entry and its hash as the `missing` it has always been.
  - **An entry another record now covers is not dropped.** Those bytes are still somebody's content, and dropping the
    entry would destroy a real claim — its digest, its algorithm, and the date saying when the file was last known
    good. It **moves** to the record that now covers it instead, which is the bullet below.
  - **Freshness does not protect an entry from pruning.** The staleness window buys a skipped *read*, and an entry that
    was never content has nothing to read; a 90-day window would otherwise leave a catalog's stale entries in place
    indefinitely.
  - **The selection is respected, and the run reports what it dropped.** *Verify Selection* over three rows may not
    quietly rewrite the two hundred it was not shown. The count joins the run's summary line and each dropped name and
    reason lands on the resource's own log ([[appendices.logging#scopes]]), the same division a legacy seed's dropped
    lines already use — entries vanishing silently is the failure mode this is written against.
- **A pruned claim moves to the record that now covers it** (#257) — the other half of the rule above, and the half
  the pruning had to wait for. An entry for a file another record owns cannot simply be dropped: its digest, its
  algorithm and the date the file was last known good exist nowhere else, and a later baseline on the covering record
  would re-read from disk and record whatever is there **now**, including bytes that rotted before the split. That is
  the argument #243 makes for a legacy manifest, reached from the other side — this is a seed from a `.checksum`
  instead of from an `.sfv`. The entry is written into the covering record under the name *that* record spells it with
  (`sub/movie.mp4` becomes `movie.mp4` under `sub/info.rehu`), and then pruned from the one that no longer covers it.
  Five decisions:
  - **The incoming claim wins**, and any resident entry of that name goes. **Provenance beats recency**: an
    `.sfv`-seeded crc32 was recorded when the files were made, where a locally-baselined XXH3 entry recorded only
    whatever was on disk the first time this app looked — so the arriving claim wins even when it is older and weaker.
  - **The date is cleared, and the verdict with it.** Neither is true of a record that has never checked the file, and
    clearing them is what makes everything downstream work with no special case: a dateless entry is never fresh, so
    the next ordinary verify reads that file whatever the staleness window says — no force, no `stale_after=None` — and
    checks it under its **own** recorded algorithm, with *Update checksums on verify* re-keying it only on a match.
  - **The covering record is written first, and the losing one after.** A failure between the two leaves the claim in
    both records, which the next run resolves; the other order loses it outright. A covering record that cannot be
    written keeps its claims where they are, so one unwritable record never strands another resource's — as does one
    that has no record yet but a legacy manifest beside it: seeding is one-way (#243), so a record created by a
    hand-over would spend that resource's one seed on the arriving names and silence the manifest's claims for
    everything else it covers. The move waits until that resource has seeded, and completes on a later run. Sweep order
    does not matter either: a claim arriving after the covering resource has already been verified is dateless, so the
    next sweep checks it.
  - **A verify therefore writes a record it is not about**, which crosses the one-resource-at-a-time assumption the
    rename barrier is built on (#241). The write happens inside that barrier's hold, so a rename of the covering
    resource waits the milliseconds it takes rather than colliding with it, and the queue is serial
    ([[appendices.task-queue#serial]]), so no second job can be verifying that record at the same moment. What is not
    covered is another process, or this app's own in-place *Delete Missing*, touching it in the same instant — the
    last-writer-wins window every record already has, one resource further away than usual.
  - **The known cost is a false alarm, never a false clean.** An incoming claim that is itself stale — recorded before
    a legitimate edit — makes the covering record's next verify report `mismatched` on a file that is fine, and
    accepting it takes a targeted Generate. It fails in the safe direction: a false alarm rather than a clean-looking
    record over bad bytes.
- **Excluded files are never reported as unexpected**, in either tier — that list comes from the same enumeration the
  record was generated over (#226), so a `Thumbs.db` a Windows browse dropped into the directory, and an edited or
  newly added screenshot, all leave a verify clean.
- The Qt app provides UI to generate and verify checksums on demand; each such operation is a task in the task queue
  ([[architecture-design#components]]), and multi-selecting many resources serializes the work rather than running it
  all at once. **Core ships generate and verify as plain callables** (#203) taking a progress callback and a
  checkpoint that is called between chunks and never caught, so a job's pause and cancel travel out untouched and core
  never learns a queue exists ([[appendices.task-queue#job-responsibility]]). **The job class wrapping them is
  `ChecksumJob`** (#204), one subclass per run, each a registered kind so a queued run survives a restart
  ([[appendices.task-queue#lifetime]]); the document's toolbar carries Verify and Generate, a run's summary reports
  through the same inline strip every other finding uses, and the detail lands on the resource's own log
  ([[appendices.logging#scopes]]). Progress counts
  **bytes, not files** — a tutorial is
  three eight-gigabyte videos, and a bar that moves three times in twenty minutes says nothing.

- **The per-file surface is a dock on the document** (#244), hidden by default beside the two inspection docks
  (#111): one row per file, holding the path as the record spells it, the recorded status, and when that status was
  recorded — the record's UTC rendered in local time, which is not what anyone wants to read off a table. It exists
  because a verify over two hundred videos reports three mismatches into a log line, and deciding which of them is a
  legitimate repack and accepting *just that one* is the loop the targeted generate was built for. Six decisions:
  - **Rows come from the record *and* from the content enumeration.** An entry shows its status and date; a content
    file the record does not cover shows its path with both cells empty, which is what *not checked yet* honestly
    looks like — and is what makes the dock worth opening on a resource that has never been checksummed.
  - **The row number is the vertical header, not a column**, so it always numbers what is on screen: sorting by
    status renumbers `1..N` instead of carrying stale numbers down the view. A summary line under the table —
    `214 files · 210 matched · 2 mismatched · 1 not recorded` — answers *how many of what*, which the numbering
    cannot.
  - **The toolbar only checks; changing the record needs a selection.** *Verify Old* (the staleness window, named on
    the action's own label) and *Verify All* (`stale_after=None`, force) are the whole of the toolbar; *Verify
    Selection*, *Generate Selection* and *Delete Missing* live behind a right-click, where the selection is itself
    the deliberate act — so none of them needs a confirmation, and the accept-a-change loop stays unprompted.
  - **There is no blanket re-baseline over a record that already exists.** It would record whatever is on disk as
    correct, including bytes a verify has just called `mismatched` — corruption laundered into a record that then
    looks clean forever, which is the outcome the migration rule already forbids from the other direction.
    Generate stays reachable for exactly one case, a resource with **no** record, where there is no recorded hash to
    overwrite and it is the honest name for what a first run does; the toolbar shows it only then. Re-baselining
    anything else is `Ctrl+A` plus *Generate Selection*.
  - **Delete Missing is scoped to `missing` rows**, and means *the missing ones among what you selected*. Dropping
    the entry of a file that is still on disk achieves nothing — the next verify adopts it straight back, since
    `unexpected` is a report state rather than a resting one — so scoping the action removes that trap instead of
    explaining it. It hashes nothing, so it is one atomic write in place rather than a queued run: forgetting
    entries is core's third operation over a record, taking **names** rather than a status, because which entries
    deserve dropping is the view's judgement and the format is core's.
  - **An unreachable resource greys every action**, decided at the enumeration rather than from the rows: the record
    lives beside the files and shares their fate, so *this resource is not reachable right now* is the honest thing
    to draw, where an empty table would look exactly like a resource with no files (#245). The read itself is a
    directory walk and never runs on the GUI thread.

  Two more things it deliberately does not do. **The table shows the record, not the last run's report** — the two
  differ on purpose, and a view of the report would go stale the moment anything else touched the resource; the
  transient summary is the inline strip's and the log's. And **there is no progress bar here**, because the queue
  dock already shows progress per job, in bytes.
- **`Settings > Checksums` is the one place the checksum defaults live** (#242), and they reach every run: the
  **default algorithm** new hashes are recorded under, **Update checksums to {default} on verify** (the label is
  rebuilt when the algorithm changes, so it always names what it would migrate to), **Create missing checksum on
  verify**, and the **staleness window** in days, 0–1000, default 90. Both toggles ship **off**: migration rewrites
  records nobody asked to change — the first sweep over a catalog seeded from legacy manifests (#243) would re-key
  all of it — and adoption is the decision the bullet below keeps deliberate. **A window of 0 days means nothing is
  ever fresh**, so every sweep re-reads everything; the page has to say so out loud, since `0` reads just as naturally
  as *never*. The agent resolves all four when a run is enqueued and captures them into the job — core never reads a
  setting, and a restored job is *the job that was queued*.
- **A sweep verifies a folder recursively, skipping what was checked recently** (#242). The user points it at a
  folder, a walk finds every `.rehu` under it, and each resource is verified with the staleness window in force —
  which is what makes a multi-terabyte library checkable more than once. Four things follow:
  - **The records it writes are its cursor.** A sweep keeps nothing between runs: paused, quit or restarted, it walks
    again and every resource the last pass finished is skipped file by file, because their recorded dates are now
    inside the window. That is the resumability [[appendices.task-queue#cursor]] asks for, obtained from the job's own
    output — and it is *better* than a saved list of paths, which would send a resumed sweep at files that have moved.
    The granularity is the resource, since a verify writes its record once at the end of one.
  - **The walk finds every record at any depth, and each one's content is hashed exactly once** (#254). A nested
    record is not a *scan* boundary — the sweep is asked to find it — but it **is** a coverage boundary
    ([[data-model#resource-scoping]]), so the bytes beneath it belong to the inner record alone and no ancestor holds
    an entry for them. This reverses the double-verify this section used to record as accepted; the worry it was
    accepted against, that the outer record's entry for those bytes would go permanently unverified, does not arise
    once the outer record has no such entry. What such an entry becomes for a record written earlier is the pruning
    rule below.
  - **The walk excludes nothing.** The junk list is a rule about *content* files; no `.rehu` can match one, and
    letting the list decide which resources a sweep can see would let an unrelated settings edit hide a resource from
    verification. The list goes to each resource's run, where it means something.
  - **One bad resource costs itself.** A branch that will not list, a refused read or a record this build cannot parse
    is counted and logged and the sweep carries on; a resource with no record is counted as such rather than as a
    failure. The one refusal is the folder itself — a root that will not list means the run has nothing to say (#245).
    Progress counts **resources**, not bytes: a catalog's byte total is not knowable without `stat`-ing every file
    under it first, and the resource count is exact and free once the walk has run.
- **A cancelled run reports nothing it did not establish.** A verdict is only produced once a file's whole digest has
  been computed and compared, and a stop leaves through the checkpoint rather than returning a half-filled report, so
  a cancel can never manufacture a mismatch. A generate writes its record **once, at the end**, through the atomic
  writer: a stopped or crashed run leaves the previous record intact rather than a truncated one that a later verify
  would read as authority for half the resource.
- **Asking twice is not asking again** (#204). A resource that already has an unfinished job of the same kind waiting
  is left alone rather than given a second one: the queue is serial, so a duplicate would only make the first take
  longer to matter, and two identical runs over the same terabyte is never what was meant. Matched on the row a reader
  can see — the job's label and its source — rather than on an identity the surface would have to keep, which is what
  keeps it true for a job restored from the last session.
- **A verify never creates the record it is checking against, unless it was told it may** (#204, #242). By default a
  resource with no manifest is offered *Generate*, and a verify enqueued against one refuses at validation with a
  sentence naming the record rather than quietly adopting every file it finds. *Create missing checksum on verify*
  is what lifts that, and it ships off: it reaches the document's own Verify as well as the sweep, so turning it on
  makes every Verify a Generate for a resource that has no record — which is a decision, and is why it is a setting
  rather than a default.
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

**Type-directed descent (design note; replaces tc4's stop-at-first-sidecar).** Whether the scanner descends past a
directory-scoped document is a property its **type declares** (in the plugin's non-GUI core layer,
[[plugins#core-vs-plugin]]): a *tutorial* is a **scan boundary** — its nested folders are its own content
([[data-model#resource-scoping]]) — while a *collection* is not, which is what lets a containment-shaped collection's
`info.rehu` sit in the parent directory whose subdirectories are its members ([[plugins#grouping-entities]]).
File-scoped documents never terminate descent — they describe named files, not the directory. Two caveats travel with
the rule: a mis-typed boundary document hides its subtree (an optimization's failure mode — verify-on-access and
explicit notifications still reach nested files, and the scanner may cheaply flag "boundary document with `.rehu`
files beneath it", in the coexistence-warning spirit of [[data-model#resource-scoping]]); and tc4's two-phase
collect-then-parse scan existed only to give its progress bar a denominator — with parse-on-find, progress is
reported against the previous scan's totals (an estimate that is right when little changed, the common case under
incremental scanning), and a first-ever scan shows a running count instead of a percentage.

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

- [#93: feat: lock reasons — named lock causes; unparseable and missing files open locked, empty](https://github.com/borco/rehuco/issues/93)
- [#94: feat: MessageBanner — inline document notices replace modal error boxes](https://github.com/borco/rehuco/issues/94)

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
[[nodes#local-vs-swarm]]): parsing is to enforce sanity caps — total file size, `versions`-list length, entry sizes,
JSON nesting depth — so a file exceeding them opens read-only with a warning (or is refused at import) instead of
exhausting memory or wedging the app. These caps are **not yet implemented** (#88): today the reader reads the whole
file into memory before `json` parses it.

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

**A failing save gets the same treatment from the other side — a surface, not a traceback.** Reading is not the only
place file I/O can fail: a save writes bytes, and the write itself can fail transiently — most importantly onto an
**offline SMB mount** ([[mounts-and-storage#offline-mounts]]), an explicitly supported scenario. Rather than letting the
`OSError` escape as a stderr traceback (worst of all at app close, where it would abort the shutdown, #146), every save
call site funnels through **one seam** that offers a **Retry / Cancel** loop naming the failure — the Save and Upgrade
actions, Save All, the per-tab and batch close guards, and the whole-app close all share it, so the failure is surfaced
(and the choice to abort whatever the save was gating) in exactly one place. Only `OSError` is caught: a save-blocking
lock raises instead of doing I/O, but editing is disabled while a document is locked, so a lock never reaches a save
site — only the file I/O can actually fail. Cancelling means nothing was written and the caller aborts what the save was
gating (a close is called off, the dock stays open).

### §4.9.1 The lock-reason vocabulary

[[[data-model#lock-vocabulary]]]

A document opens read-only for a **named cause**, never a bare "locked" bool — so a viewer can say *why* and act per
kind, and so `save()` can refuse exactly the kinds that would clobber recoverable data. Each cause pairs a **kind** with
a human-readable **message** naming the specifics (the offending key, the parser's line/column) for the persistent
non-modal notice (#94). The vocabulary is what several layers speak — the core produces it, the agent's view-model
mirrors it, the inline notice renders it — so it lives apart from the document itself. The six kinds:

| kind | what it means | remedy |
| --- | --- | --- |
| `legacy_tc` | a legacy `.tc` mapped to the current layout, with no `.rehu` on disk yet ([[acquisition-tooling#tc-to-rehu]]) | convert, not a text edit |
| `newer_format` | the file's `format_version` is newer than this build understands ([[data-model#schema-version]]'s fail-safe rule) | upgrade this build; fields are carried verbatim, never downgraded |
| `newer_block_format` | the **active** plugin block's own `format_version` is newer than the installed plugin ([[plugins#plugin-blocks]], the per-block refinement of the fail-safe rule) | upgrade the plugin; the block is carried verbatim, never restamped |
| `invalid_field` | an owned field is **present but fails coercion** — reading coerces it for display, but a save must not write the coerced default over the malformed original | fix the named key in a text editor, then revert/reopen |
| `invalid_file` | the file exists but cannot be parsed at all (`RehuFormatError`, or a non-missing `OSError`); opens as an **empty** view bound to the path | fix the file by hand (the message carries the parser's own line/column) |
| `missing` | the file is gone (`FileNotFoundError`) — deleted between sessions, an unmounted share; same empty locked view as `invalid_file` | restore or remount the file, or close the dock |

**Which kinds block save is a split, not a severity ranking.** Three — `invalid_field`, `invalid_file`, `missing` — make
`save()` itself **refuse** (a frozen set the save path consults), because writing would overwrite a
malformed-but-recoverable field or an absent/broken file with coerced defaults or an empty document. The other three —
`legacy_tc`, `newer_format`, `newer_block_format` — **do not** touch `save()`: a `.tc` saves *through conversion*, and a
newer file or block is *carried verbatim, never downgraded* ([[data-model#schema-version]]). They are gated at the UI
(the edit affordances are disabled) rather than by refusing the write, keeping the two mechanisms — what `save()` refuses
vs. what the editor greys out — from being conflated. `missing` is kept distinct from `invalid_file` precisely so a bulk
"close vanished files" sweep never closes a dock whose file the user is mid-repair on.

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

**The agent surfaces the load-time upgrade as an explicit action.** Because the upgraded layout reaches disk only on the
first save, a file that is opened, read, and closed untouched stays at its old version on disk indefinitely. The agent
offers an **Upgrade** action (#89) to force that write on demand — but it is **not a separate migrate call**: it is
literally a **save**, since `save()` already writes the in-memory-upgraded layout ([[data-model#write-integrity]]), so it
shares the Save action's failing-save guard. It is offered **only when the on-disk file is stale** — its file-wide *or*
active-block `format_version` is older than this build — **and** the document is clean and unlocked (a dirty document
upgrades on its next ordinary save anyway; a locked one cannot be written at all, which is also why a legacy `.tc` — always
locked — is never "upgradable" and is handled by conversion instead, [[acquisition-tooling#tc-to-rehu]]). The action thus
makes visible, and available without a dummy edit, what would otherwise happen silently on the next save.

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
