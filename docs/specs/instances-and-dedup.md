# §10. Identity, Instance Tracking, and Deduplication

[[[instances-and-dedup]]]

## §10.1 UUID identifies lineage, not "the one legitimate copy"

[[[instances-and-dedup#uuid-is-lineage]]]

A single resource's UUID can legitimately exist in **many physical locations at once**, by design — a backup, a vacation
checkout, and the live copy on a node are all valid, simultaneous instances of the same resource. UUID is not
"uniqueness enforcement"; it answers **"are these the same resource?"**, enabling:

- **Corruption recovery**: if a primary copy fails checksum verification, any other known instance with the same UUID (a
  backup on an offline HDD, a USB checkout) is a candidate to restore from, verified against the checksum manifest
  before being promoted.
- **Manual backups**: the user keeps the TS-230's two drives unmirrored and does manual rsync backups onto smaller,
  mostly-offline HDDs. These backups intentionally share UUIDs with their originals.
- **Read-only/sealed media (CD/DVD)**: once burned, a disc's own `.rehu` is frozen by definition — it can never be
  reconciled back onto. The disc is treated as one more instance of the UUID, tagged read-only/sealed: useful for
  provenance and as a restore source, but never a sync target. All future edits (notes, tags, fixed typos) live on a
  separate, ordinary, mutable instance elsewhere in the swarm, linked by the same UUID — the same separation already
  used for online-only resources, where the `.rehu` is independent of the (uncontrollable) URL it describes.

## §10.2 Instance registry

[[[instances-and-dedup#instance-registry]]]

Each UUID maps to a set of known **instances**, each tagged with a role (primary, backup, checkout, mounted-elsewhere,
sealed/read-only) and a health/last-seen state. Reconciliation and dedup-recovery logic operate over this registry —
e.g. skipping sealed instances when looking for a sync target, or surfacing a healthy backup when the primary fails a
checksum check.

## §10.3 Failure model, precisely

[[[instances-and-dedup#failure-model]]]

"A node is down" and "the underlying files are unreachable" are **independent conditions**, not the same event:

- If a node is down but the files remain reachable via some mount (by the Qt app or by another node), the resource stays
  fully live and editable through that other route — no fallback needed.
- The read-only/writable-cache fallback ([[offline-editing#overview]]) applies only when **no live access route remains
  at all** for that resource — true offline media being the common case (a USB stick or disc that's physically
  disconnected most of the time), not merely "the node that happens to administer it is off."

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
   duplicate-link) while both physical instances persist in the instance registry
   ([[instances-and-dedup#instance-registry]]) — the same mechanism as backups, just discovered after the fact.
3. **Not a duplicate** — the specific pairing is recorded as rejected and must never be re-proposed, so re-scans don't
   repeatedly resurface the same false positive.

Each verdict is permanent until explicitly revisited, mirroring the system's broader principle of not re-asking
questions the user already answered (e.g. not re-suggesting a deleted/rejected resource for re-download).

**Open question**: when two duplicates merge (case 1), what happens to per-user state if both copies had independently
accumulated some (e.g. partial viewing progress on each)? The same union/merge rules from [[sync#overview]] likely
apply, but this should be a deliberate decision when dedup is designed in detail, not an assumption.
