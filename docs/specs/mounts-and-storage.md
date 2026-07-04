# §9. Mounts, `.rehuco`, and Cross-Box Visibility

[[[mounts-and-storage]]]

## §9.1 The problem

[[[mounts-and-storage#the-problem]]]

A machine running the Qt app (or a node) may have network shares from *other* boxes mounted locally — e.g. the Mac mini
has the QNAP's share mounted. The same physical files can then be reachable two ways at once: directly via the mount,
and via the QNAP's own node over REST. Naively, this risks the same resource appearing as two separate catalog entries.

## §9.2 Resolved by UUID, not by path-guessing

[[[mounts-and-storage#uuid-not-paths]]]

Path-based inference (trying to guess that a given mount root corresponds to a given node's share) is fragile — mount
points are named arbitrarily and have no necessary relation to a node's internal paths. Instead: **a resource discovered
via a mount and the same resource reported by a node are recognized as identical purely because their `.rehu` UUIDs
match.** Once matched, the catalog holds one logical entry with multiple known **access routes** (mount path, node REST
endpoint, or both), and can prefer whichever route is fastest for a given operation (typically: local mount > delegating
to a node over the network).

This same model generalizes cleanly: **more than one node can serve the same resource**, if more than one box happens to
have the owning box's share mounted. This isn't a conflict — it's just additional access routes for the same UUID. If
the originally-owning box goes down but another node still has it mounted, that node can keep serving the resource live;
the read-only cached fallback (§10) only applies when **no** live route remains at all.

## §9.3 `.rehuco`: explicit, local, declared scope

[[[mounts-and-storage#rehuco-scope]]]

Rather than relying purely on empirical UUID-matching to discover the mount-to-node relationship (which only
self-corrects after both sides have independently reported the same UUID at least once), the system uses a **`.rehuco`
file, local to each machine**, that explicitly declares:

- which folder roots this machine/app should scan or track
- for mounted roots, which node administers that content and how to reach it
- which plugins ([[plugins#overview]]) should be loaded for this machine

`.rehuco` is **per-machine, not swarm-wide** — mounts inherently differ machine to machine (different mount points,
different machines even having a given share mounted at all), so a shared/central `.rehuco` wouldn't reflect any single
machine's reality. This also removes any cold-start ambiguity: the mount-to-node relationship is known immediately at
startup, not discovered after the fact.

**Do not put swarm-identical data in `.rehuco`.** Users, hashes, and access rules are swarm-wide and must be identical
on every node; they belong with the propagated swarm registry ([[discovery-trust-access#user-auth]],
[[discovery-trust-access#access-control]]), *not* in this per-machine file. The dividing line: `.rehuco` holds what is
legitimately *different* per box (mounts, ownership flags, retention opt-ins, auth-trusted flag, plugins); the
propagated registry holds what must be *the same* everywhere (membership, users, access rules).

## §9.4 Nodes can also serve mounted (not locally-owned) content

[[[mounts-and-storage#nodes-serve-mounted]]]

The same mounting capability applies to nodes, not just the Qt app — a node can serve a resource it only has access to
via a mount from another box, using the same `.rehuco`-declared relationship.

## §9.5 Out-of-band changes: notification, verify-on-access, and scan — not disk-watching

[[[mounts-and-storage#out-of-band]]]

Ordinary agent edits to a managed `.rehu` route through the owning node ([[data-model#write-integrity]],
[[nodes#local-vs-swarm]]), so the node sees them by construction. What this section covers is the **out-of-band change**
— a write the owning node didn't make: an agent in local-file mode with no route to the node ([[nodes#local-vs-swarm]]),
files dropped in by other tools, a bulk copy landing in a watched root. The node must learn of these without a
continuously-running filesystem watcher (an unwanted resource cost, especially on weak hardware). Three complementary
discovery paths, ordered by immediacy:

1. **Explicit notification (fast path).** Whoever made the change and knows — via `.rehuco` — which node administers the
   path sends a lightweight **"re-read this specific resource"** notification, keyed by UUID/path. If the node is
   unreachable at that moment, the notification is queued as a retryable task ([[architecture-design#components]])
   rather than lost — it is not the sender's job to keep retrying by hand. A burst of rapid edits to the same resource
   is debounced into a single outgoing notification, consistent with the coalescing rule in [[sync#overview]].
2. **Verify-on-access (lazy path).** The node's cache stores each `.rehu`'s stat signature and content hash at last read
   ([[data-model#scan-and-staleness]]); opening, browsing to, or serving the resource re-checks it, so an out-of-band
   edit is reintegrated the moment anyone touches the resource again — no notification and no scan needed.
3. **Incremental scan (catch-all).** Changes nobody announced and nobody has touched surface at the next version-aware
   incremental scan ([[data-model#scan-and-staleness]]).

On any of the three, the node re-reads just that file, updates its cache, and propagates the change onward through the
swarm as for any other metadata update, with the version-vector comparison deciding fast-forward vs. concurrent
([[data-model#write-integrity]]).

## §9.6 Node handoff during active viewing

[[[mounts-and-storage#node-handoff]]]

A user may start watching a tutorial via the node on their PC, then switch to the node on the TS-230 (e.g. because
they're shutting the PC down), and later reconnect the PC — expecting playback progress to follow seamlessly throughout.
This requires no new mechanism beyond [[sync#overview]]'s per-user state sync, but does require a **higher push
frequency during active playback**: progress should be written to the authoritative record every few seconds (or on
pause/seek/stop), not only at session end, so that switching the serving node — or reconnecting one used earlier —
reflects state that's only seconds stale rather than a full session behind. A node taking over playback reads current
state before resuming, the same read any node would perform on session start.

## §9.7 Example deployment: multiple machines mounting one share

[[[mounts-and-storage#example-deploy]]]

The same share can legitimately be mounted by several machines at once (e.g. the PC, the main desktop, the Mac mini, and
a low-power always-on Linux box could all mount the QNAP's export) — this is an ordinary network-share capability, not
something the architecture needs to specially support. What it means in practice is that **"who serves a resource"
doesn't need a single designated answer**; per [[mounts-and-storage#uuid-not-paths]], any subset of machines with access
can each run a node for it simultaneously, with no conflict. This makes per-machine role assignment a matter of matching
each box's power/compute profile to a job, rather than picking one "correct" server:

- A weak-but-already-always-on box (e.g. one already running other always-on services, with idle CPU/RAM to spare) is
  well-suited to **light, always-available serving** — answering catalog queries, serving cached metadata/thumbnails,
  proxying file reads — but should be explicitly excluded from CPU-heavy tasks (checksumming, scanning, dedup matching),
  which belong on whichever machine is being actively used at the time and has real headroom.
- The box that actually owns the disks (e.g. the QNAP) doesn't strictly need to run its own node at all if another
  always-on machine adequately covers the serving role via a mount — though running one anyway adds redundancy if its
  power/compute cost is acceptable.
- This role assignment is a deployment/configuration choice (expressed via `.rehuco` and task-dispatch tagging,
  [[data-model#checksums]]), not an architectural constraint — different households, or the same household at different
  times, could assign roles differently without any design change.

## §9.8 Configurable durable retention of remote/offline metadata

[[[mounts-and-storage#durable-retention]]]

`.rehuco` can opt in, per source, to keeping a **durable local copy of that source's `.rehu` metadata and screenshots**
— for usually-offline media (external drives, USB sticks, CD/DVD) and optionally for other nodes. Rationale and rules:

- **Why**: offline media are painful to rescan one-by-one, and a powered-off node's content would otherwise drop out of
  the catalog. Retaining their metadata locally keeps them browsable while disconnected, and — because the retained
  copies are ordinary local files — keeps them present across a full cache rebuild
  ([[architecture-design#why-distributed]]). Extending the same option to other nodes' metadata is for
  completeness/flexibility, not necessity.
- **It's opt-in and configurable** because every retained copy is, by definition, a cache that can go stale relative to
  its true owner. The cost of the convenience is more staleness surfaces; the mitigation is cheap version-marker
  staleness detection ([[data-model#scan-and-staleness]]), not frequent rebuilds.
- **Retained copies are read-only stand-ins.** They reflect the v1 rule ([[sync#overview]]): you can browse them offline
  and attach your own per-user notes, but you cannot edit the *resource metadata* of a retained copy until its real
  owner is reachable. (For genuinely write-once sources like sealed CD/DVD, the metadata is never editable on the source
  at all; edits live on a separate mutable instance, [[instances-and-dedup#uuid-is-lineage]].)
- **Staleness is resolved by version comparison, not blind overwrite.** When a retained source becomes reachable,
  compare the stored `resource_version`/timestamp against the live one; re-pull only if it moved.

## §9.9 Tolerating offline mounts without blocking

[[[mounts-and-storage#offline-mounts]]]

A node may run continuously (e.g. the always-on Linux node) while the boxes whose shares it mounts — the TS-230 in
particular, but any source box — are powered off or unreachable for long stretches. A configured mount is therefore
frequently **present in `.rehuco` but currently dead**, and the node must keep serving everything else without stalling
on it.

The hazard is concrete: on a dead SMB/NFS mount, ordinary filesystem calls (`stat`, `open`, directory listing) **block
for the mount's timeout** — tens of seconds, or indefinitely with a hard mount — so a node that naively touches a
mounted path while serving a request would wedge that request, and potentially a whole worker, on storage that simply
isn't there.

Rules:

- **Treat every mounted root as possibly-offline.** Reachability is runtime state, not config; never assume a mount is
  live just because it is declared.
- **Probe reachability cheaply and out-of-band.** Check liveness with a single bounded-timeout operation (a `stat` of
  the mount root or its fingerprint file, [[mounts-and-storage#fingerprint-map]]) run in the task queue
  ([[architecture-design#components]]), not on the request-serving path. Cache the up/down result and **back off**
  before re-probing, so a dead mount is consulted rarely and a flapping one doesn't cause churn.
- **All mount I/O is timeout-wrapped and off the hot path.** File reads through a mount run in worker threads with their
  own deadlines, so one dead mount can never block request handling or another mount's traffic.
- **Offline ⇒ serve last-known, read-only.** When a mount is offline, the node falls back to retained metadata
  ([[mounts-and-storage#durable-retention]]) and reports status `offline, showing last-known`, exactly as it does when
  no live route remains ([[mounts-and-storage#uuid-not-paths]]) — it does not hang waiting for the mount to return.
- **Recovery is a version-marker re-pull, not a rescan.** When a probe succeeds again, reconcile via the
  [[mounts-and-storage#durable-retention]] version comparison (re-pull only what moved); the mount coming back does not
  force a full rescan.

Deployment note: mount the shares **soft / with short timeouts** so failed syscalls return an error quickly rather than
hanging. Hard mounts defeat this discipline and should be avoided for swarm storage.

## §9.10 Self-mapping via fingerprint files

[[[mounts-and-storage#fingerprint-map]]]

UUID-matching ([[mounts-and-storage#uuid-not-paths]]) resolves overlaps *per resource, reactively*. Fingerprinting
resolves the **topology of shared storage proactively** — it discovers that nodeA's `foo/1` + `foo/2` and nodeB's
mounted `foo/` are the same underlying storage, and how their paths map, without waiting to observe per-resource UUID
collisions. Mechanism:

1. Each node drops a **content-unique fingerprint file** (containing a UUID identifying that node-root) into each
   top-level root it is **primary** for ([[mounts-and-storage#folder-add]]) — never into remote/mounted roots, which it
   doesn't own and which may be read-only.
2. All nodes do a fast, shallow scan looking for *other nodes'* fingerprint files, across **all** their roots — primary
   and mounted alike.
3. If nodeB finds nodeA's fingerprint inside what nodeB calls `foo/`, then nodeB's `foo/` and nodeA's root are the same
   storage, and the **relative paths reveal the mapping** (nodeA's `foo/1` = nodeB's `foo/1` under the shared root).
   This reconstructs cross-node path-mapping automatically, including asymmetric cases (A maps two subdirs separately; B
   mounts the parent whole).

Requirements: the fingerprint file must be content-unique per node-root (UUID inside), and the scan must handle
**multiple fingerprints in one tree** (B's `foo/` may contain A's *and* C's fingerprints if three boxes share it). This
same map is what detects the double-primary misconfiguration ([[mounts-and-storage#folder-add]]): if two nodes both
claim primary for storage the fingerprints prove is shared, the swarm flags it.

## §9.11 Folder-add: declaring primary/local vs. remote/mounted ownership

[[[mounts-and-storage#folder-add]]]

When the admin adds a folder root to a node (via that node's `.rehuco`, edited through the node per
[[nodes#two-roles]]), it must be tagged as one of:

- **Primary/local** — this node owns the files and is the authoritative metadata writer ([[sync#overview]]).
- **Remote/mounted** — this node serves files it reaches via a mount but does *not* own them; some other node is
  primary.

This flag is the concrete source of truth for [[sync#overview]]'s single-writer guarantee. **Hard constraint: exactly
one node may be primary for any given storage.** Two nodes both marking the same (fingerprint-proven shared) storage as
primary is a misconfiguration that breaks the single-writer guarantee; the self-mapping function
([[mounts-and-storage#fingerprint-map]]) is what detects and flags this.

## §9.12 Node benchmarking and grading

[[[mounts-and-storage#node-benchmark]]]

An explicit, user-triggered task ([[architecture-design#components]]) that produces per-node performance grades to feed
the dispatch decisions in [[data-model#checksums]]/[[mounts-and-storage#example-deploy]] (currently described only
qualitatively as "the fast box" / "the weak box"):

- Create a large test file, generate its checksum, then **clear the OS disk cache and re-checksum to measure cold-read
  speed** (not warm-cache speed).
- Assemble per-node numbers (cold read throughput, checksum throughput, etc.) into a **grade** the dispatcher uses as a
  score.

Caveat to record: dropping disk caches is disruptive and **platform-specific** (mechanism differs across
Linux/macOS/QNAP and may need privileges). The benchmark must therefore be occasional and explicit, never automatic, and
must **degrade gracefully** where cold-cache measurement isn't permitted (fall back to warm-cache numbers, flagged as
such).

## §9.13 Self-determined fastest/safest move/rename

[[[mounts-and-storage#safe-move-rename]]]

> [!NOTE]
> **Implement the cross-filesystem move with Opus, not the auto-switched Sonnet.** The copy → verify-checksum-on-target
> → delete-source-only-if-verified sequence (and keeping the source's instance-registry entry until verification passes)
> is data-loss-sensitive: a wrong ordering or a skipped verification can delete the only good copy. Override to
> `/model opus` for the cross-FS path.

The system chooses *how* to perform a move/rename rather than assuming:

- A rename/move **within one filesystem** is a near-instant metadata operation — but only when performed by something
  with **direct local access to that filesystem**. The fingerprint map ([[mounts-and-storage#fingerprint-map]])
  identifies which node is local to the files' storage; the move is **delegated to that node**, which does the instant
  in-place rename.
- The same rename issued **over SMB from a remote mount** may not be recognized as in-place and can silently degrade
  into copy-then-delete (slow, briefly doubles disk use). The design routes *around* needing to predict Samba's
  behavior: same-FS moves are delegated to a local node; anything else is treated as a cross-filesystem move.
- **Cross-filesystem moves are checksum-gated (hard rule):** copy → generate/verify checksum on the *target* (preferably
  by the node local to the target FS) → delete the source **only if verification passes**. The source retains its
  instance-registry entry ([[instances-and-dedup#instance-registry]]) until target verification succeeds, so an
  interrupted move is always recoverable and never loses data.
