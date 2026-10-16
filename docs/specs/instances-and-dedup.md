# §10. Identity, Known Copies, and Deduplication

[[[instances-and-dedup]]]

## §10.1 UUID identifies lineage, not "the one legitimate copy"

[[[instances-and-dedup#uuid-is-lineage]]]

A single resource's UUID can legitimately exist in **many physical locations at once**, by design — a backup, a
borrowed copy, and the live copy on the share are all valid, simultaneous instances of the same resource. UUID is not
"uniqueness enforcement"; it answers **"are these the same resource?"**, enabling:

- **Corruption recovery**: if a copy fails checksum verification, any other known copy with the same UUID (a backup on
  an offline HDD, a borrowed copy) is a candidate to restore from, verified against the checksum record before being
  copied back.
- **Manual backups**: the user keeps the TS-230's two drives unmirrored and does manual rsync backups onto smaller,
  mostly-offline HDDs. These backups intentionally share UUIDs with their originals.
- **Read-only/sealed media (CD/DVD)**: once burned, a disc's own `.rehu` is frozen by definition. The disc is one more
  copy of the UUID, tagged read-only: useful for provenance and as a restore source, never a save target. All future
  edits (notes, tags, fixed typos) live on a separate, ordinary, mutable copy elsewhere, linked by the same UUID — the
  same separation already used for online-only resources, where the `.rehu` is independent of the (uncontrollable) URL
  it describes.
- **A second borrow refused**: the UUID is what a borrow is checked against across every reachable node's `.borrow`
  records ([[borrowing#recording-borrows]]).

## §10.2 Known copies, without a registry

[[[instances-and-dedup#instance-registry]]]

The earlier design kept an **instance registry**: every UUID mapped to its copies, each with a role and a health state,
replicated across the swarm. There is no registry. What the app knows of a resource's copies is what the files say:

- the rows of every root's cache, keyed by root and relative path, each with the record's UUID
  ([[data-model#cache-schema]]) — two rows with one UUID under two roots are two copies;
- the `.borrow` records in each reachable node's borrow store, and the per-node snapshot of them the agent keeps for
  the nodes that are away ([[borrowing#recording-borrows]]);
- the retained copies of offline roots ([[mounts-and-storage#durable-retention]]).

That is enough to show where a resource is, to refuse a duplicate borrow, and to offer a restore source; a full rebuild
of every cache loses nothing, because each of those is a file a scan finds again.

## §10.3 Failure model, precisely

[[[instances-and-dedup#failure-model]]]

"The node is down" and "the files are unreachable" are **independent conditions**:

- A node down costs the web pages, the long jobs and the borrow store it holds, and nothing else: the agent reads and
  writes the files through its own mount as always.
- The files unreachable — the share offline — costs editing their details until they are back; the cached rows stay,
  marked offline, per-user edits queue ([[offline-editing#overview]]). True offline media (a USB stick or disc that is
  physically disconnected most of the time) are the common case of this, not a failure.

## §10.4 Deduplication

[[[instances-and-dedup#deduplication]]]

UUID matching alone is not sufficient for dedup, because two `.rehu` files can describe the same real-world resource
without sharing lineage — e.g. a copy received from someone else who generated their own `.rehu` independently, or
multiple accidental downloads of the same thing made before cataloguing existed. Dedup needs a **separate, complementary
signal set**:

- **Content checksums** (strongest signal, when files are present to compare)
- **URL matching** (useful, but uneven in reliability — see below)
- **Fuzzy matching** on title/author/size when neither of the above is available

**URL specificity must be tracked explicitly.** Some `.rehu` entries carry a real, unique URL (a specific product/course
page); others, where the original page no longer exists, were backfilled with a generic publisher homepage as a
placeholder. These look identical as plain strings but mean very different things for matching — treating them the same
would cause false-positive dedup matches concentrated exactly on resources whose metadata is already weaker. The schema
should mark generic/fallback URLs explicitly (e.g. a flag, or a separate field from a confirmed specific source URL) so
dedup logic can exclude them from the match signal rather than being misled by them.

## §10.5 Duplicate review UI

[[[instances-and-dedup#duplicate-review]]]

Automated matching only ever **proposes**; a human verdict is recorded and never re-asked:

1. **Confirmed duplicate, keep one** — user picks the canonical copy; the other(s) are marked appropriately (e.g.
   tracked as a known extra copy, consistent with not silently losing track of removed items) rather than deleted with
   no record.
2. **Confirmed duplicate, keep both** — e.g. different rips/quality. Lineage converges (shared UUID, or an explicit
   duplicate-link) while both physical copies persist where they are — the same thing as a backup, discovered after the
   fact.
3. **Not a duplicate** — the specific pairing is recorded as rejected and must never be re-proposed, so re-scans don't
   repeatedly resurface the same false positive.

Each verdict is permanent until explicitly revisited, mirroring the system's broader principle of not re-asking
questions the user already answered (e.g. not re-suggesting a deleted/rejected resource for re-download).

**Open question**: when two duplicates merge (case 1), what happens to per-user state if both copies had independently
accumulated some (e.g. partial viewing progress on each)? The per-field merge rules of [[sync#compare-and-swap]] likely
apply to the two sidecars, but this should be a deliberate decision when dedup is designed in detail, not an
assumption.
