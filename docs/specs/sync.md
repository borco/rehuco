# §7. Sync & Conflict Resolution

[[[sync]]]

## Overview

[[[sync#overview]]]

> [!NOTE]
> **Implement this with Opus, not the auto-switched Sonnet.** The version-vector ordering, the concurrent-edit merge
> rules, the delete-vs-edit asymmetry, and the tombstone semantics are reasoning-dense — a subtle error here silently
> loses or resurrects data. Override `opusplan` to `/model opus` while implementing [[sync#overview]] even though it's
> "execution," and verify each merge case against the rules below.

Two different kinds of data live in `.rehu`, with different natural owners:

| Data | Examples | Owner | Conflict risk |
| --- | --- | --- | --- |
| Resource metadata | author, duration, description, screenshots | The node administering the files (per `.rehuco`, [[mounts-and-storage#rehuco-scope]]) | None — only one logical owner ever writes it; others hold cached, version-stamped copies |
| Per-user state | view progress, notes, bookmarks, borrow records, deletion/archival actions (logged, [[sync#overview]]) | The user | Real, but narrow in scope |

**Resource metadata** never has a multi-writer conflict, by design — there's exactly one owning node per resource. Other
nodes/clients show a cached copy, marked offline/stale if no live access route remains
([[instances-and-dedup#failure-model]]). This also covers offline
media (external drives, USB sticks, CD/DVD): the cached entry persists and is marked offline rather than disappearing.

**v1 scope decision — metadata is editable only when the resource is online; per-user notes/state are always editable.**
To keep the single-writer guarantee above *actually true* rather than contradicted by offline-editing features
([[borrowing]], [[offline-editing#overview]]), the first implementation deliberately forbids editing **resource
metadata** (including
screenshots, [[data-model#image-meanings]]) while the authoritative copy is unreachable. (Editing the file itself in
local-file mode is *not* "offline editing" in this sense — the `.rehu` on disk **is** the authoritative copy; what v1
forbids is editing a *cached copy* of an unreachable resource. A direct local write to a managed file is the out-of-band
case of [[data-model#write-integrity]]/[[mounts-and-storage#out-of-band]] and reintegrates via verify-on-access,
[[data-model#scan-and-staleness]].) What remains editable offline is **per-user state** — notes, progress, bookmarks,
borrow records — which is single-user and merges cleanly. This removes the hardest distributed problem (two divergent
offline edits to shared metadata) from v1 entirely, with no loss of the actually-valuable offline capability (taking
notes on vacation). See [[offline-editing#overview]] for how this narrows the writable-cache concept.

**Future hook, not built in v1:** offline metadata editing *may* be enabled later, gated behind a merge/diff tool
(text-diff for metadata fields, old/new side-by-side comparison for screenshots — both straightforward library work,
deferred only because the UI doesn't pay off until offline metadata editing exists). To keep that path open cheaply,
**metadata carries `resource_version` markers from day one even though v1 never has to act on a metadata conflict** — so
a future merge tool has the version history it needs. Build the storage for future merge now (free); defer the merge UI
(not free).

**Per-user state** can genuinely conflict, but in a bounded way — never general multi-node consensus. Ordering is
determined by a **version vector**, not by wall-clock time:

- **Version vector (ordering, never pruned).** Each resource carries a small per-node-counter vector —
  `{nodeA: 5, nodeB: 3, …}`. A node bumps its own counter on each action it makes. "Newer" means "dominates
  component-wise"; if neither of two vectors dominates, the change is genuinely **concurrent** and must be reconciled.
  This is clock-independent (immune to the skew across Win/Linux/Mac/QNAP), and it is deliberately *lighter than git*
  (no content-addressed DAG/merkle tree) and *far lighter than a crypto ledger* (no signing chain — tamper-evidence
  isn't needed in a trusted household swarm). The vector is tiny (one integer per node that ever participated) and is
  **never pruned** — dropping a node's counter would reintroduce ordering ambiguity and resurrection-style bugs.
- **Version history (`versions`) — one list that is both the version record and the activity log.** Each resource
  carries an append-only `versions` list; every entry is one meaningful event, `{ index, date, hash, log }`: `index` is
  a monotonic per-resource counter (assigned by the owning node as it integrates the event); `date` is wall-clock,
  display/context only (ordering never depends on it); `hash` is the content hash of the `.rehu` as written by that
  event (the same hash verify-on-access compares, [[data-model#scan-and-staleness]]); `log` is the human-readable
  comment — "archived by B (reason: low quality)", "resurrected from local copy by A" — modelled on a GitLab issue's
  Activity feed. The commentary is **not a separate structure**: understanding a change means comparing two versions, so
  the *what and why* lives on the version entry itself (the vector only says *that* something diverged). "This file is
  at version 8, last touched June 3" reads straight off the list. `log` is optional per entry, but stripping comments is
  no size defense — more entries can always be minted — so oversize protection is the read-time sanity caps of
  [[data-model#write-integrity]], not field-stripping. The `index` is deliberately *not* the ordering mechanism — a flat
  index cannot represent divergence (two concurrent editors would both mint an 8; that detection is the vector's job
  above), and chaining hashes into a parent-linked DAG is exactly the git-shaped machinery this design avoids. An
  out-of-band edit's entry receives its final index when the owning node reintegrates it
  ([[data-model#write-integrity]]). There is **no silent pruning**: the only way history shrinks is **compaction as a
  logged event** — a deliberate, never-automatic action that replaces an *interior* range with a single marker entry
  (`{ indexes: 1–19, date, hash, log: "compacted 19 versions by X" }`) which keeps the count and explains the gap to any
  uncompacted copy compared later. Compaction never touches the creation entry (index 0 — it anchors the derivable
  `created` date, [[field-schema#record-timestamps]]) or the current state-defining entry (the newest
  delete/archive/resurrect).

Reconciliation rules over this model:

- **Newest action wins, by vector comparison.** If one side's vector dominates, it wins outright (the common case — e.g.
  you edited a note on the laptop, nothing changed at home). If neither dominates (true concurrency), fall to
  field-level merge below.
- **Field-level merge for concurrent edits** (no user prompt needed): watched segments (union), bookmarks (union by
  position), viewed flags (logical OR). Free-text notes (and edited screenshots, if offline metadata editing is ever
  enabled, [[sync#overview]] future hook) are the fields that can genuinely collide; worst case, keep both and surface
  for the user. Data is never silently lost.
- **Deletion, archival, and resurrection are ordinary logged actions in this same model** — not a separate mechanism. A
  deletion's "tombstone" is simply the delete event's position in the version vector: a node offline during the delete
  sees, on reconnect, that the delete vector dominates its last-known state and applies it; a rescan that re-finds the
  on-disk `.rehu` does *not* resurrect it, because the tombstone vector dominates the file's last-known edit vector.
  This closes the resurrection bug without any special-casing.
- **Asymmetric stakes for delete-vs-edit (the one nicety).** Edit-vs-edit losing the older edit is acceptable. But a
  delete silently winning over a concurrent edit (losing someone's work), or an edit silently resurrecting something
  deliberately deleted, are bad surprises — so a delete that is *concurrent with* an edit does not auto-apply; it
  surfaces in the duplicate-review-style verdict queue ([[instances-and-dedup#duplicate-review]]) for a human decision.
  Plain delete-vs-delete needs nothing (both agree).
- This reconciliation is **not limited to a single two-party case** (home vs. one checkout). It generalizes to any
  number of independent edit sources reconciling one after another — each event merges against whatever the current
  state is at that moment ([[offline-editing#overview]]).
- **Multiple edits during one continuous offline period are not a conflict among themselves** — they're sequential
  against one evolving local state, coalesced into a single outgoing sync on reconnect
  ([[mounts-and-storage#out-of-band]]).
- **Active playback progress** is pushed frequently (periodically during playback, and on graceful stop), so switching
  the serving node or reconnecting a previously-used one reflects state at most seconds stale, not a whole session
  behind ([[mounts-and-storage#node-handoff]]).
- **Hand-edited files are ordinary out-of-band changes.** A user can always open a `.rehu` in a text editor and change
  anything — fields, old log entries, even the vector. Verify-on-access catches it like any out-of-band write
  ([[data-model#write-integrity]]/[[mounts-and-storage#out-of-band]]); on reintegration the node takes the file's
  *fields* as the user's intent but treats its own cached bookkeeping as authoritative for *history*: the change lands
  as one new logged event, and a hand-mangled vector/log is repaired from the node's cache rather than trusted. (An
  *unmanaged* file needs no such resolution — there is no swarm state to protect.) Old entries' hashes are historical
  markers of the file as written at that event, not a verification chain — a later edit does not invalidate them;
  [[sync#overview]] deliberately has no tamper-evidence in a trusted household.
