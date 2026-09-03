# §18. Reference Images: Scanning, Regions, Search, and Practice

[[[reference-images]]]

## Overview

[[[reference-images#overview]]]

- [#221: feat: browse a reference-images resource's content images (read-only viewer)](https://github.com/borco/rehuco/issues/221)

This document is the full treatment of what [[plugins#refimages-plugin]] lists in four bullets: tagging the
images inside a reference-images resource's archives, using those tags to browse and search them, the
non-destructive blur of intimate regions, and a timed practice mode. **Nothing in it is built.** It is an
overview and wish-list, written so that the parts already decided by other specs are named as such, and the
parts still open are marked open rather than quietly designed. Each section opens with its status:

- **decided** — follows from an existing spec, or was settled here; a later change is a change to this document.
- **proposed** — a recommended shape with its reasoning, expected to hold but not yet exercised by code.
- **wish-list** — what is wanted, in the user's terms, with no design attached.
- **open** — deliberately not designed yet; listed in [[reference-images#open-questions]].

The scale governs everything: packs hold hundreds to ~20 000 images, the whole collection is in the order of
**10 million images and 3 TB** (with duplicates), and full inference over it is measured in GPU-weeks, not
minutes. A design that is fine at 500 000 images is not automatically fine here.

## §18.1 Purpose and scale

[[[reference-images#purpose-and-scale]]]

**Status: decided.**

The catalog exists to serve **drawing practice and reference**, not general retrieval. The user does not
mainly want a search-result list; they want a sequence of images they did not choose, on a timer, matching an
aim — "male heads from different angles", "fat woman reclined", "male with sword and shield", "female
standing", "draped woman", "fists", "ankles". Search is the substrate; the practice session
([[reference-images#practice-sessions]], [[reference-images#modes]]) is the product, and the Pinterest-like
browse is how a starting point or a similar image is found.

Most packs are pose references, but not all: animals, flora, cityscapes, ruins, military vehicles and the like
are in the collection too. Those must be **tagged** like everything else, and must **not** acquire body regions
or blur regions — which falls out of the pipeline's shape rather than needing a rule
([[reference-images#scan-sidecar]]).

Two surfaces, matching the two resource families: tutorials get an Udemy-like follow interface
([[plugins#tutorial-plugin]]); reference images get a Pinterest-like one. Both are served on the desktop by
the agent and, later, in the browser by a node ([[architecture-design#components]]).

## §18.2 Three data layers, each with an existing home

[[[reference-images#layers]]]

**Status: decided in outline.**

[[data-model#image-meanings]] already fixes *where* per-image metadata lives: app-managed, beside the `.rehu`,
never inside the immutable checksummed zip. What this section adds is its *shape*: there are three kinds of
per-image data, and each already has a home in the data model.

| Layer | Holds | Home | Ownership and sync class |
| --- | --- | --- | --- |
| **Machine-derived** | per-image tags with confidences, an image embedding, detected person / head / hand / foot boxes, detected blur boxes, keypoints, 360° sequence membership, a ~512 px working image, and the model that produced each | the **scan sidecar** beside the `.rehu` ([[reference-images#scan-sidecar]]) | resource metadata: written only by the resource's primary node ([[mounts-and-storage#folder-add]]); travels with the folder; a bookkeeping suffix like `.checksum`, so it never counts as content ([[data-model#checksums]]). **Rebuildable in principle, at GPU-weeks cost — so retained and copied like screenshots, never treated as `.rehudb`-disposable** |
| **Shared authored — the admin default** | an admin's corrections: regions and blur boxes added, moved, resized or deleted; manual 360° groupings; per-image shared tags | the `reference_images` block of the `.rehu`, inline, **sparse** (only images someone touched) | resource metadata: single writer, online-only edit in v1 ([[sync#overview]]); the layer every user sees by default |
| **Per-user** | favorites (image keys), per-user region and blur overrides, the user's blur-on/off preference | the block's `users.<name>` map ([[field-schema#per-user-shared]]), sparse | per-user state: mergeable, offline-editable, writable through any node |

**Render-time merge rule: the scan provides, the admin layer overrides, the current user's layer overrides
that.** "Other users" is a *view* of their `users.<name>` entries and is never merged into anyone's rendering.
The viewer offers the three as a toggle — **default (admin)** / **current user** / **other users** — which is a
presentation rule in the spirit of [[field-schema#per-user-shared]]'s table rather than an access boundary:
private is not secret, and the file is readable by anyone who has it. Editing a region while viewing another
user's layer writes into the **current user's** entry, never theirs — that is the requested "user override".

Why the machine layer is not `.rehudb`-class, restated: the design's rule that a derived cache is disposable
([[data-model#local-file-trio]]) assumes rebuilding is cheap. Here it is the most expensive thing the system
ever does. Data that costs weeks to recompute must travel with the resource, so that copying a pack to
another machine delivers it already scanned — a cache-only design cannot do that. And why it is not *inside*
the `.rehu`: at a few kilobytes per image a 5 000-image pack becomes a 17 MB document, which the whole-document
load, preserve-unknown and atomic-save rules ([[data-model#rehu-format]]) would rewrite on every rating edit and
which every folder browse would parse to collect a title. That is a read-granularity problem, solved by a
second file — not by moving the data off the resource.

## §18.3 Image identity and staleness

[[[reference-images#image-identity]]]

**Status: decided.**

All three layers key an image the same way, and there are **two keys, for two costs**:

- **Tier-0 key: the member name, its uncompressed size, and whatever per-member fingerprint the container's
  own directory already records — tagged with the container kind that supplied it.** This is not a choice of
  hash algorithm; it is a refusal to read the bytes. A zip's central directory holds a CRC32 per member, so
  keying a whole archive costs one directory read and **inflates nothing** — the whole 3 TB is keyed in
  minutes. XXH3 ([[data-model#checksums]]) here would mean inflating every member first, which is the full read
  the tier-0 pass exists to avoid. `ContentImageScanner` (`rehuco_core.rehu_content_images`) already enumerates
  a zip's central directory without decoding; today's archive set is `.zip`/`.cbz` (`ARCHIVE_EXTENSIONS`).

  The key is therefore **`(container kind, name, size, container fingerprint)`**, and each part is there for a
  reason the others cannot cover. The **name** is the address — it gives the zip-order browse and is what a
  person recognizes — but alone it cannot say whether the image at that address is still the same one: a pack
  refreshed with a re-exported `012.jpg` keeps the path and changes the picture, and a hand-placed blur box
  would then sit on the wrong body. The **fingerprint and size** answer "did the thing at this address change?"
  without reading a byte; size alone cannot (a re-encode can land on the same size) and the member's mtime
  cannot either (a zip stores it at two-second DOS granularity and re-packs routinely reset it). The reverse
  case — the same bytes under a **new** path after a renumbering re-pack — is what the durable key below is
  for. A new container format adds a row to a small table rather than a new identity scheme: 7z headers carry
  a CRC32 per member; RAR headers carry a CRC32 (RAR5 optionally BLAKE2); a tar, or images loose in a folder,
  carry **nothing**, and
  their tier-0 key degrades to `(kind, name, size, mtime)` — weaker, and honest about it. Two rules keep this
  sound: the fingerprint is compared **like with like only** (a zip CRC32 is never compared to a 7z CRC32, even
  though the algorithm is the same — the kind is part of the key), and **a container-kind change is a key
  change**: re-packing a zip as a 7z invalidates every tier-0 key, which is exactly the case the durable key
  below exists to repair. A format is added only under the licensing policy
  ([[packaging-deployment#licensing-policy]]) — `zipfile` is the standard library; 7z and RAR readers bring
  their own license and, for RAR, a decompressor dependency that must be checked before it is promised.

  This key drives the zip-order browse, change detection on a re-pack, and the stale-overlay warning
  [[data-model#image-meanings]] asks for: when a member's tier-0 key changes, every authored-layer entry keyed
  to it is flagged, not silently rendered over the wrong picture.
- **Durable key: XXH3 of the member's bytes, recorded during tier 1** ([[reference-images#scan-sidecar]]) —
  the scanner inflates every member then anyway (decode once, fan the pixels out to every stage), so the app's
  own default algorithm is folded in at no extra I/O. This is the identity for **cross-pack deduplication** (the
  duplicates in the 3 TB, feeding [[instances-and-dedup#deduplication]]) and for re-attaching authored layers
  when a member is renamed, re-packed byte-identically, or **moved to a different container format** — the
  bytes of a JPEG are the same whether a zip, a 7z or a folder held them, so XXH3 is the one key that survives
  every re-pack. A container fingerprint's 32 bits are far too collision-prone at ten million images to carry
  that role: they only ever say "probably unchanged", and XXH3 confirms.

Sort order for the zip-order browse is **natural** (`image9` before `image11`), not lexical; the zip's own
member order is otherwise preserved.

## §18.4 Practice sessions are per-user documents

[[[reference-images#practice-sessions]]]

**Status: proposed; deferred.** Practice mode is deliberately the last thing in the RefImages family
([[implementation-plan]]) — the browser, blur and Pinterest browsing come first. The shape below is recorded
so the earlier slices leave room for it, not because it is next.

A practice run spans packs, so its record has no single `.rehu` to live in. The precedent is the **learning
path** ([[plugins#grouping-entities]], [[field-schema#learning-path-ownership]]): a per-user, metadata-only
document in the user's configured creation directory ([[mounts-and-storage#rehuco-scope]]). A **practice
session** document holds the prompt or filter it was generated from, its schedule (for instance ten 30-second
poses, five 2-minute, two 10-minute), and the ordered list of `(resource UUID, image key)` pairs shown, with
timestamps and whether each was skipped. The last N sessions are kept; older ones are pruned, which is the
retention setting the user asked for ("the last couple of practice runs").

**Favoriting from a past session writes into the *resource's* block** — a per-image favorite in
`users.<name>`, the same per-image mechanism used everywhere else ([[plugins#refimages-plugin]] already says
this) — so favorites outlive the session document that surfaced them. "Find similar" from a past session is a
query, and stores nothing.

This also answers where practice history lives when a pack is borrowed ([[borrowing]]): it is per-user state,
so it syncs like notes and progress do ([[sync#overview]]), and a session whose images are on a pack that is
now unreachable shows them as offline rather than losing the entry ([[instances-and-dedup#failure-model]]).

The timer, next/skip, and full-screen presentation are the **shared timed-presentation capability**
[[plugins#shared-capability]] already asks for; this is its second consumer after "follow tutorial".

## §18.5 The scan sidecar

[[[reference-images#scan-sidecar]]]

**Status: proposed.** The file's name, container and schema are the things most likely to change once code
exists; what is firm is that it is one per-resource file of machine output, beside the `.rehu`.

- **Name:** `<stem>.rehuimg` — `info.rehu` → `info.rehuimg`, the same stem rule as `info.checksum`. It joins
  the `.rehu*` family ([[architecture-design#overview]]) because it is a rehuco-owned format; `.checksum`
  stayed generic because its *concept* is. It is a **bookkeeping suffix**: never content, never checksummed,
  never counted in a size ([[data-model#checksums]]).
- **Container: SQLite, one file.** Chosen over a JSON or NDJSON-plus-blobs directory because re-running one
  stage is an `UPDATE` rather than a rewrite, a transaction leaves an interrupted scan valid, one file is what
  copies and syncs cleanly, `mode=ro&immutable=1` works on a read-only mount, and a stored image is read by
  offset without materializing rows — `Connection.blobopen()` locates the row by id and streams only that
  blob's pages, so a grid costs one open handle and a few page reads per cell. Stored images live in **their
  own table**, so reading tags never drags image pages through the cache. The costs are accepted and named: it is opaque binary,
  so a `dump` command must exist; and it carries its **own schema version and migration chain** exactly as
  `.checksum` does (`rehuco_core.migrations`), stamped with an `application_id` so that a foreign file at that
  path is recognized and never written into or deleted — the `.rehu`'s own claim rule, applied to a sibling.
- **Stages are tiered so a pack is useful long before it is fully scanned**, and each stage is independently
  re-runnable, its model recorded per row ([[reference-images#model-contracts]]):

  | Tier | Produces | Cost | Needs |
  | --- | --- | --- | --- |
  | **0** | member list from the central directory, image dimensions from headers | seconds per pack | nothing beyond the zip |
  | **1** | XXH3, the working image, image embedding, tags with confidences, blur boxes, person boxes, 360° grouping | milliseconds per image | one decode per image; the tagger, detector and embedder |
  | **2** | whole-body pose → person / head / hand / foot regions, per-person attributes, head angles | tens of milliseconds per image | the pose model, on a **person crop from the original** (below); runs only where tier 1 found a person |
  | optional | captions, prop boxes | up to hundreds of milliseconds | on demand, prioritized by the packs the user opens; may never complete |

  **Non-people images stop after tier 1 by construction**: no person detected means no region rows and no
  blur rows, which is the requested rule with nothing to configure.

- **Decode once.** JPEG decode, not inference, is the first bottleneck at this scale; every model wants an
  input around 400 px, so the decoder's DCT-scaled draft mode is used and the resulting array is shared by
  every stage. This is an implementation note recorded here because it decides the pipeline's shape (a decode
  pool feeding a batch queue), not a tuning detail.
- **Probabilities are stored, never booleans.** Whether a box is blurred or an attribute is shown is a
  threshold applied at render time, so changing a threshold is a preference, not a rescan.
- **One stored image per member — a working image, not a thumbnail.** Tier 1 keeps the decoded image it ran
  on, at about **512 px on the long edge** (WebP; a few tens of KB), as a blob in the sidecar. It does three
  jobs for one blob, which is what justifies costing three to four times what a 256 px thumbnail would:
  - **Browse placeholder** — every grid, wall and history view renders from it, downsampled
    ([[reference-images#modes]]).
  - **Re-run input** — every *image-level* stage (tags, embedding, blur boxes, person boxes, similarity) takes
    an input of 224–448 px, so a model swap re-runs those stages from the stored images in days, without
    re-inflating the archives. This is the "swap the tagger in two years" case of
    [[reference-images#model-contracts]], made cheap.
  - **Offline fallback** — a pack whose archive sits on an offline mount stays browsable from its sidecar
    ([[mounts-and-storage#offline-mounts]]); only "open full size" reports offline.

  Where 512 px is **not** enough is tier 2: a hand in a full-frame 512 px image is a few dozen pixels, and a
  pose model wants the *person crop* at roughly 256×192 to 384×288. Tier 2 therefore **crops the person from
  the original** in the archive — one seek plus one inflate, since the sidecar records each member's local
  offset — and runs at crop resolution. Tier 2 runs only where a person was found, so this touches the
  archive for a fraction of the collection.

  The size is a plugin setting, **stamped per row like a model**, so changing it is detected and the images
  regenerate lazily rather than invalidating the scan; regeneration is decode-only but still the full read of
  the collection, so the default is chosen once with care. There is no hard minimum; below roughly 128 px
  nothing on screen can use it, above roughly 512 px the store stops being a store of working images. Blobs
  sync as one sequential read per pack rather than thousands of stat calls over SMB; the storage budget and
  any eviction remain open ([[reference-images#open-questions]]).

The web-session handover that seeded this document carried a fuller schema sketch and model table; they are
deliberately not reproduced. What survives of them is above; the rest is implementation.

## §18.6 The cross-pack index

[[[reference-images#cross-pack-index]]]

**Status: proposed.**

Nothing sidecar-shaped can answer a query across packs. The cross-pack index — one roaring bitmap per tag
over dense image ids for filtering, a binary-quantized approximate-nearest-neighbour index over embeddings
for similarity and text queries, full-text search over tags — is **`.rehudb`-class** ([[data-model#local-file-trio]]):
a node-local derived cache, disposable, and **built by reading sidecars, never by running models**. That is
what makes "rebuildable cache" true here: delete it and it is back in an hour, because the expensive part
lives in the sidecars. Whether it is tables inside `.rehudb` or a sibling file is left to the CacheDB-era
implementation ([[implementation-plan]]).

A query such as "jumping female with sword" is a bitmap intersection as a cheap prefilter, a join to person
regions with the right attributes, a rerank by embedding similarity against the encoded query text, fused
with a pure-embedding lane so a mis-tagged image still surfaces. Pure embedding search is bad at exact
filters; pure keyword search is bad at "woman leaning backwards over something"; the fusion is the design.

## §18.7 The inference package

[[[reference-images#inference-package]]]

**Status: proposed.**

The models and their runner are an **optional fourth package** — `rehuco-vision`, name provisional — for the
same structural reason [[packaging-deployment#three-packages]] rejected extras: an extra cannot subtract a
dependency, and a 2–3 GB torch wheel must never be reachable from a default install. It is non-GUI, runs on
`onnxruntime` by default (its GPU and DirectML variants swap in with no change above the backend interface),
and downloads models into a cache directory on first use — **nothing is bundled in a wheel**.

The `reference_images` plugin's non-GUI core layer ([[plugins#core-vs-plugin]]) consumes it through one
`InferenceBackend` protocol with a method per stage. When the package is absent every derived field is null
and everything else — tier 0, the zip-order browse, the authored layers, favorites — keeps working. This is
[[plugins#core-vs-plugin]]'s "a missing plugin degrades to the common fields" applied one layer down.

Inference is **always local**. Hosted vision APIs refuse or sanitize nude figure reference, and the packs are
not to be uploaded regardless.

## §18.8 Model contracts: user-configurable per stage

[[[reference-images#model-contracts]]]

**Status: proposed.**

Each scan stage — tagger, blur-region detector, pose and regions, embedding, and the optional caption and
prop stages — is a **named contract**: an input shape, an output schema, and for taggers a vocabulary map.
The plugin's settings page (the "Plugins" settings group, [[appendices.settings-pages#overview]]) lists, per
stage, *which model fills it*. Three kinds of entry are foreseen:

1. **Built-in defaults** — permissively licensed ONNX models, declared as download descriptors (URL, hash,
   license) and fetched on first use. The candidates the handover named are of the WD14 tagger, NudeNet
   detector, RTMPose/DWPose whole-body pose, and SigLIP/OpenCLIP embedding families; every one is a candidate,
   not a commitment, and each is license-checked before it is added.
2. **A user-supplied ONNX file** for the same contract — a different tagger, a newer detector, a fine-tune.
   The stage adapter validates the input/output shape and, for a tagger, requires a vocabulary map.
3. **A local out-of-process endpoint** — HTTP on localhost, or a subprocess the user runs. The handover proposed
   this for captions (an Ollama- or LM Studio-style server); it generalizes to every stage.

**Licensing, restated as a design rule rather than a prohibition** ([[packaging-deployment#licensing-policy]]).
The author's freedom to license the application is compromised only by what rehuco *ships, imports or
downloads*. So rehuco never depends on, imports, or fetches an AGPL package (Ultralytics YOLO is the concrete
case) or AGPL-licensed weights — none is in the built-in list. A user who installs such a model themselves and
points a stage at it, as an ONNX file they exported or as an endpoint they run, is making a choice about their
own machine; rehuco's side is a contract and a configuration entry, and the out-of-process route keeps even
the combined-work question away from the codebase. This is the project's position, not legal advice; the safe
default is the permissive built-ins.

**Every row records the model that produced it** — name, hash, contract version — and this is what makes
user-chosen models workable rather than merely permitted: a pack scanned by tagger A and another by tagger B
are distinguishable, one stage is re-run with a new model without touching the others (a tagger swap two
years from now must not cost another six-week rescan of embeddings and working images), and the cross-pack index
can tell what it may merge. Two consequences are open ([[reference-images#open-questions]]): how an arbitrary
tagger's vocabulary maps onto the search vocabulary, and the fact that embeddings from two different models
are not comparable at all.

## §18.9 What a node needs

[[[reference-images#node-requirements]]]

**Status: proposed.**

| Operation | Needs the image bytes? | Needs inference? | Needs the cross-pack index? | Writes |
| --- | --- | --- | --- | --- |
| **Catalog (scan)** | yes — every image, decoded once | **yes**, every stage | no | the scan sidecar — resource metadata, so **the primary node writes it** |
| **Pinterest front** — browse, fuzzy text, similar | working images from sidecars; the original on click | **only the text encoder** (query string → vector, a small model); without it, the tag/fuzzy fallback [[plugins#refimages-plugin]] already names | yes | per-user favorites — per-user state, **any node** |
| **Practice front** | full-resolution images, streamed the way a tutorial's video is | no | yes, for the filter | the practice session document and favorites — per-user, **any node** |

So scanning is the only operation that needs heavy compute, and the only one that writes resource metadata.
The two fronts are ordinary serving over the cache plus per-user writes, and **any node that serves a catalog
can run them** — exactly as it serves tutorial browse and watch — provided it can reach the sidecars (own disk,
a mount, or a retained copy, [[mounts-and-storage#durable-retention]]) and, for full images, the archives
themselves or a node that has them.

## §18.10 Scan dispatch in a swarm

[[[reference-images#dispatch]]]

**Status: proposed.**

There are no designated scanner nodes as a hard role. Instead, **capabilities are advertised per node and
work is dispatched by grade** — the mechanism [[mounts-and-storage#node-benchmark]] already defines for
checksums, with one more dimension:

- **`.rehuco` declares whether this node may scan** (it has the inference package; optionally a GPU). Per-machine
  is the right scope ([[mounts-and-storage#rehuco-scope]]): "this box has a GPU" is a fact about a box. The
  benchmark job additionally grades inference throughput, cold and warm.
- **A scan is a claimable, resumable work unit** keyed on the resource UUID and the archive's tier-0 identity,
  run as a persistable task-queue job ([[appendices.task-queue#home]]) on a **second queue** — the inference
  lane, alongside the disk lane, exactly the "a second queue over a different resource, never a concurrency
  count" rule of [[appendices.task-queue#serial]]. Claimable units are designed in from the first single-worker
  version, because farming a backfill across two or three machines is the use case that justifies the
  headless node, and retrofitting claimability is far worse than building it.
- **Dispatch order for a resource whose primary node is P:**
  1. **P itself**, if scan-capable — bytes local, write local, the single-node base case
     ([[multiplicity#single-node-base]]).
  2. **A scan-capable node that reaches the same storage through a mount** the fingerprint map proves
     ([[mounts-and-storage#fingerprint-map]]): it reads the archive over the mount, computes, and **posts the
     results to P**, which writes the sidecar.
  3. **A scan-capable node with no route**: P **streams the archive** to it (REST, range requests), and the
     results come back the same way. At LAN speeds 3 TB is a matter of hours against GPU-weeks of compute, so
     streaming is a legitimate fallback rather than a hack — but it is the fallback, not the design.
- **The write is always P's.** A remote scanner never touches the sidecar; the result post-back is a plain
  REST job like a checksum report ([[nodes#overview]]), which keeps the exactly-one-primary rule of
  [[mounts-and-storage#folder-add]] intact without a new exception.
- **Sequence collapsing is the largest cost lever.** A 72-frame turnaround needs the expensive tiers on a
  handful of keyframes; the rest inherit sequence-level fields, and only blur boxes are genuinely per-frame.
  360° detection therefore runs **early in tier 1**, before anything expensive, so the collapse is schedulable.

## §18.11 Modes and viewers

[[[reference-images#modes]]]

**Status: wish-list; the browser is first.** What is wanted, in the user's terms; the interaction design is not
started. The order of building is the browser, then blur, then Pinterest browsing ([[implementation-plan]]);
practice mode is deferred ([[reference-images#practice-sessions]]).

- **Browse a pack as it is** — the archive's members in zip order with natural sort
  ([[reference-images#image-identity]]). This is #221's surface, and needs only tier 0. Its tracer needs
  **no sidecar and no model**: `ContentImageScanner` already enumerates the members, the lightbox already shows
  one image with prev/next, and what is missing is a grid over the entries with asynchronous decode (image in
  a worker, pixmap on the GUI thread, newest request first so a fast scroll never decodes rows already gone)
  and an image-source seam in place of the lightbox's `list[Path]`, since an archive member has no path. The
  sidecar's working images follow immediately after, because a first grid over a 20 000-image pack otherwise
  decodes for the better part of an hour.
- **Where pixels come from, by surface** — the rule tutorials already follow for video. Grids, Pinterest
  walls, similar-image views, practice history and the region sub-dock's overview render the sidecar's
  **working image** ([[reference-images#scan-sidecar]]), so the whole browse front works from sidecars alone,
  archive reachable or not. Full view, the practice display on a large screen, region editing at zoom, and
  export read the **original from the archive** — a 512 px image upscaled to a 3440 px monitor is
  unacceptable, and a blur box must be drawn over the pixels the user will actually see. The working image is
  shown **first, as a placeholder, and swapped for the original when it arrives** — progressive, never
  blocking on the archive; an unreachable archive leaves the placeholder and says so.
- **Pinterest-like search** — a fuzzy text box; empty text picks a random starting image. Clicking an image
  shows it large together with similar images, so browsing is a walk through neighbourhoods rather than a
  result list. "Similar" needs no model at query time (the embeddings are stored); text needs the encoder or
  the tag fallback ([[reference-images#node-requirements]]).
- **Practice mode** — a prompt selects a pool; random images from it are shown quickly, like a drawing class
  ([[reference-images#practice-sessions]]). The last few runs are remembered per user so an image can be
  favorited or used as a "similar" seed afterwards. Display transforms that cost nothing and help — random
  horizontal flip, grayscale, value posterization — belong here.
- **Favorites** — per image, per user ([[reference-images#layers]]).
- **Blur** — off by default, an app-wide toggle with a keyboard shortcut, remembered per user. Detection
  always runs regardless of the toggle: boxes cost nothing to store and cannot be added retroactively without
  a rescan. Exposure attributes remain useful for *filtering* ("clothed only" is a legitimate practice
  filter), which is selection rather than occlusion. Blur is the **first stage the inference package
  ships**: the detector finds body parts on the whole image directly, so it needs no person stage, a
  non-people image simply yields no boxes, and the render-only half (boxes, toggle, shortcut, threshold)
  lands before any authored layer or editor.

## §18.12 The region and blur sub-dock

[[[reference-images#region-editor]]]

**Status: open — wish-list only.** The interaction design is deliberately not started; this section records
what is wanted so the decision is made later on purpose rather than fallen into.

- Every reference-images document gets a **sub-dock** for one image at a time.
- It shows **two previews**: one with every region drawn and the selected region editable; one showing only
  the blur regions, with the blur on/off toggle applied so the effect is seen as it will render.
- **Body regions** (person, head, hands, feet, …) can be selected, moved, scaled and deleted; **blur regions**
  can additionally be added.
- Which layer is shown and edited follows [[reference-images#layers]]: the admin default, the current user,
  or other users; editing while viewing someone else's layer creates the current user's override. Whether a
  logged-in admin edits the shared layer directly or the same override path with a "promote to default"
  action is one of the open questions.
- A user edit is marked as such and is **never overwritten by a re-run** of the stage that first produced
  the region.

## §18.13 360° sequences

[[[reference-images#sequences]]]

**Status: detection proposed; use open; deferred.** Nothing in the earlier slices depends on sequences
([[implementation-plan]]); the one thing they must not do is store anything that would make a later sequence
field awkward to add, which the per-image keying of [[reference-images#image-identity]] already guarantees.

Many pose packs are turnarounds — 12, 24, 36 or 72 frames of one figure. Identifying them is mostly not
machine learning: natural-sort the members, segment by the regular filename patterns these packs use, then
confirm with the smoothness of consecutive embedding similarity, background constancy, and above all **loop
closure** (a full turnaround's last frame is near-identical to its first, which is what separates it from a
partial arc or a burst of similar poses). Manual groupings and corrections are an authored-layer field
([[reference-images#layers]]). A detected sequence is what makes [[reference-images#dispatch]]'s collapsing
possible.

How sequences are *used* is not decided. Two ideas are recorded without commitment: surfacing a matching
sequence as a first-class result ahead of loose images for "head from different angles"-type queries; and a
practice drill that shows one frame, lets the user draw, then reveals a frame some degrees around to check
the mental rotation.

## §18.14 Open questions

[[[reference-images#open-questions]]]

Local to this document; the global list is [[appendices.open-questions#still-open]].

- The sub-dock's interaction design ([[reference-images#region-editor]]), and whether an admin edits the
  shared layer directly or promotes an override.
- The sidecar's final name and whether SQLite holds; the `dump` command's format.
- Tag-vocabulary mapping for a user-supplied tagger ([[reference-images#model-contracts]]) — a mapping file
  per model with the built-ins' shipped, unmapped tags kept raw and searchable, is the likely floor.
- Mixed-model embeddings: the index either refuses to merge them or keeps one index per embedding model.
- Whether the Pinterest front needs the text encoder on every serving node or delegates encoding to a
  scan-capable node (a string in, a vector out — tiny).
- The working-image storage budget (~300–500 GB at 512 px over ten million images) and whether any eviction
  is wanted; whether region crops are materialized lazily per region kind or always cut from the original.
- Practice-session retention (how many runs), and what a session records beyond what was shown.
- What 360° sequences are for ([[reference-images#sequences]]); the keyframe count for collapsing.
- Whether per-image tags feed dynamic access grants ([[discovery-trust-access#access-control]]) — nothing to
  design until grants exist.
- Sampled rather than exhaustive human review: at ten million images one percent uncertainty is a hundred
  thousand images, so thresholds tune for recall, user deletions are the review signal, and no queue is
  ever worked through — recorded as a stance, not yet a design.
