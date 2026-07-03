# §11. Borrowing, Library-Shelf Storage, and Scheduled Archival

## §11.1 The "library shelf" pattern

A box holding original content (e.g. the QNAP) can be treated as a library shelf that's normally **closed** — deliberately powered fully off, not just idle, to save power/wear — with content **borrowed** onto an always-on machine when the user wants it reachable, and the shelf reopened (powered on) only when needed again. This is a distinct, deliberate workflow, different in kind from both:

- a **checkout** (§7) — leaving home with a copy, syncing back later — and
- the **implicit offline cache** (§12) — content becoming unreachable unexpectedly.

Borrowing is planned and user-triggered, may last an arbitrary length of time (not bounded by a trip), and its motivation is specifically to allow the source box to be powered fully down rather than idling.

## §11.2 Mechanism: another instance role, not a new system

A borrowed copy is just another entry in the instance registry (§10.2), tagged with a role such as `local-borrow`, alongside `primary`, `backup`, `checkout`, `mounted-elsewhere`, `sealed`. It's created the same way a checkout is (verified copy, snapshotted base state) and reconciles back using the same rules (§7) once the source becomes reachable again — "the QNAP was off for a while" is functionally identical to "a checkout was offline for a while" from the reconciliation engine's point of view. While borrowed, the local copy is a fully live, fully-featured instance (not a degraded cache) for as long as it exists, regardless of how long the source stays powered off (§10.3).

Two things worth deciding deliberately when this is built (not resolved here):

- Whether powering the source down/up is manual or automated (e.g. a scheduled shutdown after a period of no active node traffic, with Wake-on-LAN to bring it back on demand).
- Borrowing is inherently per-resource and selective — worth treating as a deliberate user action ("borrow this") rather than something that could be confused with bulk replication of the whole library.

## §11.3 Scheduled archival of a borrowed resource

The user can mark a borrowed resource **to be archived on return**: rather than simply deleting the local borrowed copy, the goal is to shrink the *original* (or whichever instance becomes the long-term one) by removing large video files, while deliberately keeping `.rehu` metadata, the `infoXX.*` images, and other explicitly-preserved extras (e.g. code-example zips). This is a structural change to what the resource contains, not a lifecycle/visibility change like the tagging or duplicate-review mechanisms elsewhere in this doc — though it's recorded using the existing tagging mechanism (§4.1) rather than a new schema field. A few consequences worth tracking precisely:

- **"Archived" is a tag, not a new schema state.** It's applied to the resource using the same general-purpose tagging mechanism already used elsewhere (§4.1), not a dedicated field or enum value.
- **`complete` is never touched, before or after archival.** Per §4.1, `complete` reflects whether all expected files were present *at cataloguing time* and is not revisited afterward for any reason — archiving (or any other later, deliberate file removal) does not flip it, set it, or otherwise interact with it. It is write-once-at-creation, full stop.
- **Two archival granularities.** The user can choose to archive **everything** (keep only `.rehu` and images, remove all video) or **selectively** (keep a chosen subset of files in addition to `.rehu`/images — e.g. one or two representative/interesting videos), so archival is not strictly all-or-nothing on the video content.
- **Execution is deferred until a live route exists.** Archival is scheduled as a task (§3) that stays pending — the same way a node-change-notification waits when its target is unreachable (§9.5) — and executes the moment the source (or any node/route with the resource mapped) becomes reachable again, i.e. when the "shelf" is reopened.
- **The checksum manifest is purged, not flagged.** Once a file is removed by archival, its entry is deleted outright from the checksum manifest, rather than retained with an "intentionally removed" marker — the manifest should only ever describe files that are actually still present.
- **Archiving the original does not affect the borrowed copy's lifecycle.** The two are decoupled: marking/executing archival on the original does not automatically delete the local borrowed copy. The borrowed copy's own removal (or continued retention) remains a separate decision for the user to make independently.
- **The action is effectively irreversible** for the files it removes — once gone, they're recoverable only from a backup instance (§10.2) if one exists, not from the archived resource itself.

## §11.4 Recording borrows in the user's meta block

A borrow is recorded as an entry in the **user's meta block inside the resource's own `.rehu`**, rather than only in a separate registry. This makes a borrow self-describing and self-cleaning, consistent with the rest of the design:

- **Multiple simultaneous borrows are a list, not a flag** — `(device id, borrowed-at, optional expected-return)` per entry — so the same resource can be borrowed onto more than one *node-capable* device at once (e.g. a laptop and a desktop), each tracked independently. Note: a borrow target must be able to run a local node and hold the copy; the iOS tablet cannot be a borrow target (§11.5).
- **An explicit "return" step removes that device's entry.** Borrow is declared, return is declared; the absence of an entry means not-borrowed. No heuristic inference of borrow state.
- **Because the borrow record lives in the resource's `.rehu`, it survives a cache rebuild** wherever that `.rehu` is reachable or retained (§2) — unlike a purely transient instance.

Two caveats, since they're this approach's failure modes:

- **A borrow taken while the source is offline can't be written into the source's `.rehu` immediately** — which is the normal library-shelf case (§11.1), where the owner is deliberately powered off. The borrow is recorded locally on the borrowing device and synced into the resource's meta when the owner next comes up, subject to the same deferred eventual-consistency rules as any other per-user-state edit (§7/§12). A borrow record is per-user state, not instantaneous global truth.
- **Stranded borrow entries need a visible manual cleanup path.** A lost/wiped device that never performs "return" would otherwise leave its entry lingering forever. At household scale, a manual "clear this borrow" in the admin/editor UI suffices (no auto-expiry needed), but the UI must surface borrow entries so a stranded one is visible and removable. An optional expected-return date lets the UI flag an overdue borrow without auto-removing it.

**Mental model — OneDrive Files On-Demand.** The borrow/normal/archived-stub states map cleanly onto OneDrive's three states: archived-stub (metadata + screenshots only, §11.3) ≈ online-only placeholder; a normal node-resident copy ≈ locally available; a borrow ≈ pinned/"always keep on this device." The analogy is good for vocabulary but breaks on consistency: OneDrive has a single always-available cloud authority behind all three states, whereas this system's authority is distributed and sometimes deliberately powered off — so the *states* transfer but the *sync-back/reconcile* model (§7) does not.

## §11.5 Thin tablet and the vacation topology

The iOS tablet is a **pure thin web client** — deliberately, because no native app will be published for it. This has firm consequences:

- **The tablet can never hold a borrow or any per-user offline state.** It has no local node and no local resource storage; it only ever *views* what a reachable node serves over HTTPS. ("Borrow onto the tablet" is therefore not possible — corrected from an earlier example.)
- **Away from home, the laptop's own node is the tablet's server.** The canonical vacation topology: the laptop runs a node that holds the borrowed resources *and* serves the web UI over HTTPS to the tablet, reached over LAN or the laptop's hotspot. This means the **laptop node must run the web-server role**, not just the desktop Qt app.
- This reinforces the off-LAN boundary (§A03.2): there is no "tablet reaches home over the internet" path. The tablet always talks to a *local* node — a household always-on box at home, or the laptop while away.

## §11.6 Resolving a borrow when the resource was deleted or archived meanwhile

While user A has a resource borrowed, user B may delete it (everything, including metadata) or archive it (keeping only metadata, screenshots, and explicitly-selected files) back in the swarm. Because **A's borrowed copy is a complete, valid instance (§10.2)**, B's action is never destructive to A — it's a divergence to resolve on A's return, with A's copy available as a recovery source. The version vector (§7) detects the divergence; the activity log (§7) tells A *what B did and why*.

On A's return, A is offered three choices in both cases:

- **Drop** — A agrees with B; A's local copy is discarded too.
- **Archive from local** — keep metadata/screenshots/selected files using A's copy.
- **Resurrect from local** — A overrides B's opinion; A's complete copy is promoted back. Resurrection is itself a logged action with a new vector position that dominates B's delete, so when B's node next syncs it sees "resurrected, newer than my delete" and the resource correctly returns on B's side too, with the log explaining why.

The difference between the two cases:

- **B fully deleted:** the swarm has nothing; the three choices operate purely on A's copy.
- **B archived:** the swarm has the stub; "resurrect/archive from local" **merges** A's fuller copy with what B kept — A's copy contributes the files B dropped, the stub contributes any metadata edits B made meanwhile.

**B's deletion reason is always preserved and surfaced to A** (carried in the activity log), so A sees *why* B removed it before deciding — and may come around to agreeing with B later. This is the same "never silently lose a human's reasoning" principle as the deletion-with-memory feature (§10.5).
