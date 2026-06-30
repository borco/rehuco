# rehuco — Architecture Design

*rehuco — a personal, distributed catalog for tutorials, references, and creative assets.* (The name is the stem of the file formats it owns: `.rehu`, `.rehuco`, `.rehudb`, `.rehusw`. Successor to TutCatalog, generalized beyond tutorials.)

## 1. Problem Statement

The user has a large, heterogeneous personal media collection spread across multiple machines:

- Local video tutorials (flat or nested folder structures)
- Online tutorials (YouTube and other resources, sometimes mixed with local files)
- Udemy course registrations (large, poorly catalogued, mixed quality)
- Zip archives of reference images, Daz3D plugins, and 3D objects
- Likely more categories over time

Scale: 1–20 users (household), but 5,000–10,000+ tutorials and hundreds to thousands of other resources.

An existing PySide6 app already manages this using a YAML sidecar file (`info.tc`) per tutorial folder, with an SQLite cache layered on top to solve load-time problems as the catalog grew. The next generation of the system needs to:

- Replace `info.tc` (YAML) with `info.rehu` (JSON) — ~10x faster to parse per the user's benchmarks
- Scale across multiple physical machines, not just one
- Support offline/disconnected use (laptop, USB stick, optical media)
- Support multi-user access control at household scale
- Support a web interface for low-power hardware (QNAP) and tablet access
- Support extensible resource types via a plugin model

## 2. Why a Distributed, Self-Describing Design

Two properties drive most of the architecture:

1. **Self-describing data.** `.rehu` files live next to the content they describe. A resource can be copied, moved to a different disk, moved to a different node, backed up, checked out, or read from completely offline media (USB stick, CD/DVD) — and it still carries everything needed to reconstruct its catalog entry. The cached database (SQLite or similar) is rebuildable from scratch by rescanning `.rehu` files; it is a cache, never the source of truth.

   **Precise rebuildability boundary** (refined from earlier discussion): not *all* state is rebuildable purely by scanning files reachable at rebuild time. Two categories need care:

   - **Retained metadata copies** of usually-offline sources (external drives, USB sticks, CD/DVD) and optionally of other nodes, kept locally per `.rehuco` opt-in (§9.8). These *are* rebuildable-by-rescan, because they're stored as local files a scan will find — that's the whole point of retaining them, so an offline DVD's catalog entry doesn't vanish during a rebuild just because the disc is on a shelf.
   - **The instance registry's knowledge of transient instances** (e.g. an active checkout on a laptop currently elsewhere) is *not* reconstructable by scanning local files — nothing local records that a copy is out in the world. These are allowed to be forgotten on a full rebuild and to re-register themselves when they next reconnect/sync (§10.2). Borrows are a partial exception: because a borrow is recorded in the user's meta block inside the resource's own `.rehu` (§11.4), it survives rebuild wherever that `.rehu` is itself retained or reachable.

   The practical implication: full rebuild-from-scratch is still supported, but it is no longer entirely "free" — it forgets transient, non-retained instances. The old habit of frequent full rebuilds (driven historically by the absence of schema migrations and by stale-data anxiety) should be retired in favor of schema migrations plus cheap, version-aware incremental reconciliation (§4.6), with full rebuild demoted to a rare recovery tool.

2. **No single always-on machine.** The user's hardware is heterogeneous (Windows 11 PC, Debian Linux PC, Mac mini M1, QNAP TS-230 NAS) and not all of it is equally reliable or powerful. Rather than design around one central server, the system is built as a **swarm of peer nodes**, each capable of answering for itself, and each tolerant of any other node — or any other *resource's storage* — being unreachable.

This pushes the design toward a **distributed system with eventual consistency**, not a client-server app with a single backend. That's a deliberate, scope-increasing choice — worth stating plainly, since it affects build order and where complexity lives.

## 3. Components

**Core principle — the agent (desktop GUI) is a node client for swarm operations; "admin" is a logged-in user's privilege, not a separate app (§5.1).** The desktop GUI talks to a node rather than touching the catalog filesystem itself, removing "local path vs. remote node" special-casing. The bare single-file viewer is the one exception — it opens a local `.rehu` off disk with no node and no login (§5.3).

| Component | Role |
|---|---|
| **Agent** (PySide6 desktop GUI) | Tray icon, viewer/editor, catalog/admin UI. A node client (§5.1). Exposes admin functions only when an admin *user* is logged in (§6.7) — there is no separate "admin build". Runs only on machines with a display. |
| **Local viewer/editor** (part of the agent) | Views/edits a single `.rehu` file. Registered as the default `.rehu` handler in File Explorer (double-click opens it, §5.4). Works in local-file mode with no node/login (§5.3). Behavior is supplied by the resource's **plugin** (§13). |
| **Node** | Headless service: watches folder roots, serves `.rehu` data over REST, participates in the swarm, runs jobs. Runs on every machine including headless ones (QNAP). No GUI. Multiple per machine (different config/data dirs, ports). Per root, **primary/local** (owns files, authoritative writer) or **remote/mounted** (serves a mount it doesn't own) — chosen at folder-add (§9.10). Independent lifecycle from the agent (§5.1). |
| **Task queue / dock** | Visible, app-wide queue of slow operations (checksum, sync, scans, copies, node-notify, benchmarking, safe moves). Pause/resume/cancel/reorder. Multi-selecting serializes work rather than running it all at once. All background swarm chatter lives here, surfaced as status not a blocking gate (§5.2). |
| **Web interface** | Served by a node for browser access — primarily the iPad/tablet, a pure thin client (§11.5) that only views what a reachable node serves over HTTPS and never holds offline state. At home: a household always-on node; away: the laptop's node over LAN/hotspot. Rendering supplied by the resource's plugin. |
| **Plugins** | Define resource types (tutorial, reference images, Daz3D, future). Own schema extensions, viewer/editor UI, web rendering, and custom actions (§13). |

## 4. Data Model

### 4.1 `.rehu` format

JSON, replacing the YAML `.tc`. The full schema is being designed separately and isn't detailed here, but its scope is settled:

- **Common fields**, available to every resource type regardless of plugin: `title`, `url`, `size` (on disk), `date`, `description` (Markdown, can embed local images).
- **Plugin-specific fields**, defined per resource type, e.g.:
  - *Tutorial*: `duration` (general), `progress` (per user)
  - *Daz3D*: `installed` (per user, per box)
  - *Reference images*: `count` (general), `tag` (general and per-image), `mosaic` (per-image redaction regions)

See §13 for how plugins own their field sets without the core app needing to understand their shape.

A few field-level decisions carried over from the old `.tc` format, worth keeping in mind when the schema is finalized:

- `date` must support partial precision — year only, year+month, or full date — with sensible comparison/sorting across mixed precision.
- Fields like publisher/title and learning-path membership must support **multiple values**, not a single scalar — the same tutorial can be sold on more than one platform under slightly different names, and can belong to more than one learning path.
- A field like the old `online` flag means "is the original source still available," not "is this an online-only resource" — worth being careful that the new schema's naming doesn't repeat that ambiguity.
- A field like the old `complete` flag means "are all expected files present," unrelated to viewing/watching status.
- Old single-purpose boolean flags (e.g. `keep`) are being replaced by general-purpose tags rather than carried forward as dedicated fields.
- Some fields (publisher, title, author, date) are also used to generate candidate folder-name suggestions, which the user picks from to rename a resource's directory — a convenience feature carried forward from the old app. With multi-valued fields, this needs a notion of a "primary" value per field to build the suggestion from, with others as alternates.

### 4.2 Stable identity, independent of location

Because resources can move between folders, disks, and nodes, **path cannot be the identifier**. Every `.rehu` carries a UUID minted once at creation time. This UUID identifies the **resource's lineage** — see §10 for why this is a many-to-one relationship (one UUID, potentially many physical instances) rather than "one UUID, one legitimate copy."

### 4.3 Single file, not split metadata/state files

Considered splitting `.rehu` into separate metadata vs. per-user-state files to simplify conflict resolution, but rejected this: it breaks the "one self-sufficient file" property that makes the design work in the first place. Instead, conflict resolution is scoped to the relevant sub-block *within* the one file (§7).

### 4.4 Resource scoping: directory-scoped vs. file-scoped

Two patterns for what a `.rehu` describes:

- **Directory-scoped**: `info.rehu`, alongside `infoXX.jpg/png/gif` images and an `info.sfv`/`.md5`/`.sha256` checksum manifest. Covers tutorials (flat or nested) and folder-based resources generally. The checksum manifest covers everything in the directory **except** `info.rehu` and the `infoXX.*` images, so description/images stay freely editable without invalidating integrity checks.
- **File-scoped**: `foo.rehu` + `foo00.jpg`, `foo01.jpg`, ... + `foo.sfv`/`foo.md5`, describing a single file like `foo.zip`. This needs to extend to **multiple files** treated as one logical resource (e.g. `foo.zip` + `bar.zip` together) — naming convention alone can't express that, so the `.rehu` must carry an explicit manifest block listing which file(s) it describes.
- **Coexistence**: a directory may end up containing both a directory-scoped `info.rehu` and one or more file-scoped `*.rehu` entries (normally this shouldn't happen — it's meant to be one or the other). Rather than forbid this outright, the app caches and displays all such entries and flags the situation with a warning, leaving resolution to the user.

### 4.5 Checksums

- Algorithm in use today: CRC32 (SFV). Subject to change pending benchmarking (CPU-accelerated CRC32 vs. alternatives like xxHash or hardware-accelerated SHA). The checksum manifest format should record **which algorithm was used** per entry, so a future algorithm switch doesn't invalidate or require migrating existing checksums, and different resources can use different algorithms if needed.
- Checksums cover only **immutable original content** — the actual tutorial/resource files — never `.rehu` or the `infoXX.*` images, which are designed to be freely editable.
- The Qt app provides UI to generate and verify checksums on demand; each such operation is a task in the task queue (§3), and multi-selecting many resources serializes the work rather than running it all at once.
- **Execution location is a dispatch decision, not fixed.** A checksum job can run: (a) on the node that owns the files (cheapest when the Qt app would otherwise have to pull bytes over the network just to hash them), (b) in the Qt app directly against a locally/mount-accessible path (cheapest when that path is faster than going through a node's API, or when no node is reachable at all — e.g. an offline checkout on a USB stick), or (c) via a locally mounted path that happens to also be served by a node — see §9.4. The general rule: **prefer whichever route gives local-disk-speed access to the actual bytes**; fall back to delegating to the owning node otherwise.

### 4.6 Two distinct meanings of "image"

The design uses "image" for two unrelated things; conflating them caused real ambiguity, so they're separated explicitly:

- **Screenshots (`imageXX.jpg`/`.png`/`.gif`)** — app-managed presentation metadata that accompanies a `.rehu`. Editable, **not** checksummed, part of the editable record (subject to the online-only-editing rule for resource metadata in v1, §7/§12). These are what "images" refers to in the viewer's image strip and in description embeds.
- **Content images inside a reference-image zip** — part of the **monolithic, immutable, checksummed resource**, exactly like a tutorial's video files. The app never edits these. Refreshing such a zip is a deliberate, manual, out-of-band action that also requires manually refreshing its checksum; it is not done through this app.

The reference-images plugin's per-image tags and redaction overlays (§13.3) describe *content images inside the zip* but are stored as **app-managed mutable metadata alongside `.rehu`/screenshots**, keyed to images inside the zip by index/filename — they never modify the immutable zip. Consequence worth handling: if a zip is manually refreshed (new content, new checksum), per-image overlays may now point at the wrong images. The app should detect the checksum change and warn that per-image overlays may be stale, rather than silently rendering redactions over the wrong images.

### 4.7 Scanning strategy and staleness detection

Scanning is load-bearing (§2, §9.5) but the *strategy* was previously undefined. Two principles:

- **Incremental, version-aware reconciliation is the normal mode; full rescan is a recovery tool.** A node/app should detect what actually changed (e.g. by file mtime/size, or by comparing a cheap `resource_version`/timestamp marker) and re-read only those `.rehu` files, rather than re-parsing the whole catalog on the hot path. The original startup-slowness problem was a full-scan problem; the SQLite cache plus incremental scanning — not raw per-file parse speed — is the real lever. (JSON-over-YAML is still chosen for tooling, validation, and benchmarked parse speed, but parse speed of a single file is not the primary startup-time factor once the cache exists.)
- **Retained copies record the version they were copied at.** Any locally retained copy of another source's metadata (§9.8) stores the source's `resource_version`/timestamp at copy time, so staleness is a cheap version comparison when the source is reachable again — not a full re-read. This bounds "am I looking at stale data?" to a fast check, removing the historical motive for nervous full rebuilds.

### 4.8 Per-node local file trio

Each node keeps three files of the same basename, sitting together, with sharply different roles and lifecycles:

| File | Holds | Category | Lifecycle |
|---|---|---|---|
| `.rehuco` | Per-machine config: folder roots, mounts, primary/remote ownership flags (§9.10), plugin list (§13), retention opt-ins (§9.8), auth-trusted flag | Local, legitimately *different* per box | Authored locally; never propagated |
| `.rehudb` | The SQLite catalog cache | Derived cache | Rebuildable within the §2 boundary; disposable/regenerable |
| `.rehusw` | Swarm info: membership, users + salted hashes, access rules | Swarm-identical, *propagated* | **Durable, not disposable** — updated by resync, never regenerated from scratch |

`.rehusw` is the concrete on-disk home of the propagated registry that §6.5–6.9 refer to abstractly. Crucially it is **not** treated like `.rehudb`: a cache rebuild must not wipe it, because a node that is offline (and may rebuild its cache) must still remember the last-known users/access rules so it isn't blind until it can resync (§6.10). It is persisted state that gets *updated*, not regenerated.

### 4.9 Write integrity: atomic writes + single-writer-per-managed-file

A `.rehu` is the source of truth, and several actors can want to write one (an agent edit, the owning node's metadata writes, sync reconciliation). Two writers touching one file at once would corrupt it. Two mechanisms compose to prevent this — and which applies depends on whether the file is **managed** (a node owns its storage, §9.10) or **unmanaged** (a loose file no node watches — a fresh export being adjusted, a single file received from someone, anything in local-file mode §5.3):

- **Atomic write is universal — every `.rehu` write, by anyone, is temp-then-rename.** Write to a temp file in the same directory, fsync, then atomically rename over the original (POSIX same-FS rename; Windows `ReplaceFile`/`MoveFileEx`). A reader never sees a half-written file, and a crash mid-write leaves either the complete old file or the complete new file — never a torn one. This prevents *torn* files.
- **Managed files: the owning node is the sole writer.** Any edit to a managed `.rehu` — whether it originates in the agent, in sync reconciliation, or in the node itself — goes *through the owning node*, which serializes all writes to that file. The agent never writes a managed `.rehu` directly; it sends the edit to the node (it is already a node client for swarm operations, §5.1) and the node applies it atomically. This makes racing writers structurally impossible: there is definitionally one writer. (Consequently the §9.5 "agent edits through a mount, then notifies the node to re-read" path is **narrowed/retired for managed files** — the agent asks the node to make the change rather than writing the file the node also writes. The notify-and-rescan path remains only for changes a node wasn't told about, e.g. files dropped in by other means.) This prevents *racing* writers.
- **Unmanaged files: the agent writes directly, atomically.** No node exists to route through (local-file mode, §5.3), so the agent writes the file itself using the same temp-then-rename discipline. The single-instance design (§5.4) already prevents two agent windows from contending; atomic write makes even a pathological double-write lose-one-rather-than-corrupt.

**Import is the explicit unmanaged → managed hand-off.** A received export (unmanaged, stripped of swarm bookkeeping per §6.8) is edited freely in local-file mode (agent writes directly). **Import** is the discrete act of a node taking ownership — assigning the file to a primary root and minting fresh swarm bookkeeping (new version vector, instance entry, §10.2). Before import, no node knows the file exists (agent is sole writer); after import, exactly one node owns it (node is sole writer). There is no window where both believe they own the write, because import is a deliberate, atomic transition. At import the node treats the file as untrusted outside input — validate it, upgrade its format if older (§4.10), mint new bookkeeping — rather than assuming it is well-formed just because it has a `.rehu` extension.

### 4.10 Schema format versioning of `.rehu` itself

The `.rehu` schema will gain fields over time (it is still being designed). Because the offline-media design (§9.8, §10) guarantees old files *will* resurface years later — off a USB stick, a sealed DVD, a received export — every `.rehu` must carry its own **format-version field**. Rules:

- **A newer agent/node reads an older file and upgrades it** to the current format on write (the upgrade is itself an atomic write, §4.9, and for managed files happens through the owning node).
- **An older agent/node encountering a newer file must fail safe, not lossy.** It must not silently drop fields it doesn't understand and write the file back — that would quietly delete data. It should refuse to write (read-only view), or preserve unknown fields verbatim on round-trip. The cheap robust default: **preserve unknown fields untouched** so a round-trip through an older version never loses data.
- **Import is a natural upgrade point** (§4.9): a received older-format file is upgraded as the node takes ownership.
- This replaces the historical "rebuild the whole DB on every schema change" habit (§4.7), which only existed because the old app lacked both DB migrations *and* file-format versioning. With a format-version field plus DB migrations, schema evolution no longer requires a destructive full rescan.
- **Plugin fields are versioned per-block, not under the file-wide version** (§13.1a): each plugin's keyed block carries its own independent format version, so a plugin's schema can evolve without bumping the common-field version or any other plugin's. The same upgrade/preserve-unknown rules apply at block granularity.

## 5. Node Communication

**Plain REST over HTTP**, not a message queue or pub-sub broker. The actual operations needed (query catalog, fetch content/thumbnails, push state sync, trigger a remote checksum job, notify a node that a file changed, serve a browser) are simple request/response patterns. A queue would add infrastructure (broker, persistence) with no real benefit at this scale, and would burden the weakest hardware (QNAP TS-230). REST is also natively browser-compatible, covering the tablet/web-UI case for free.

Nodes need to support, at minimum:

- Serving `.rehu`/catalog data (read)
- Accepting metadata/state updates (write, subject to ownership rules in §7)
- Accepting an async "please checksum these files and report back" job, pollable for progress
- Accepting a lightweight "re-read this specific resource, it changed" notification (§9.5)
- **Browsing the node's own local filesystem** (list directories/files) so the admin app can build folder selections against the *node's* reality, not the app's machine (§5.1, §9.10)
- Accepting and reporting **benchmark jobs** (§9.11) and **safe-move jobs** (§9.12)
- Dropping/creating **fingerprint files** and reporting found fingerprints for auto-mapping (§9.9)

### 5.1 Two roles: node (service) and agent (desktop GUI)

The thing loosely called "the app" or "the admin app" elsewhere is more precisely the **agent**. Two distinct *roles* exist, because one process cannot be both a headless server (on the QNAP, no display) and a GUI (PySide6, needs a display):

- **Node** — the headless service: HTTP server, swarm participation, serving data, running jobs. Runs on every participating machine *including* headless ones (QNAP). Never has a GUI.
- **Agent** — the desktop-only GUI: tray icon, viewer/editor windows, catalog/admin UI. It is a **node client** — it talks to a local (or remote) node over the same HTTP/socket interface everything else uses. On a headless machine there is a node and *no* agent.

On GUI desktops the node and agent usually ship together and feel like one tray app; on the QNAP the node runs alone. The key rule: **the node role must not depend on the agent role existing**, because on headless boxes it won't. "Admin" is a property of the **logged-in user**, not of the agent (§6.7) — the agent exposes admin functions only when an admin user is authenticated; there is no separate "admin build."

**Independent lifecycles.** Quitting the agent (the GUI) leaves the local node running — it's a service that should keep serving the swarm, the tablet, and other nodes even when the desktop GUI is dismissed (like closing a mail client's window while background sync continues). Stopping the node is a separate, more deliberate action (it takes that machine's content offline to the swarm). The node runs as a service/daemon or launch-on-login, independent of the tray.

**The agent is a node client for swarm operations** (catalog, per-user state, sync, anything access-controlled): it never reads/writes the catalog filesystem directly, so there is no "local path vs. remote node" dual code path — it always asks a node, which optimizes how to satisfy the request (own disk, mount, or delegating). The mount-vs-node access-route optimization (§9.2) lives entirely inside nodes. Editing a node's `.rehuco` browses *that node's* filesystem via the node's remote-browse capability (§5 list), not the agent's machine. (Exception: the bare single-file viewer needs no node at all — see §5.3.)

### 5.2 Readiness is per-operation, never one global gate

The app must be usable before swarm chatter settles. The mistake to avoid is a single `node_is_ready` flag that blocks everything until the slowest background task finishes. Instead, operations are tiered by what they actually depend on:

- **Local-file only** → never waits. Double-clicking a `.rehu` to view it reads that one self-describing file (and its sibling screenshots) off disk and renders immediately — no swarm, no registry, no cache, no login required.
- **Local cache** → waits only on the local `.rehudb` load (or shows results progressively as it loads), never on the network. Browsing/searching the catalog is stale-but-local until background sync refines it.
- **Current access rules** → the *only* tier the serve-after-resync gate (§6.10) blocks, and only for **serving access-controlled resources to a user**, and only when there is genuinely newer access data to catch up to (the version-marker check). A node that missed nothing, or a single node (§8.1), satisfies it instantly.

All swarm activity — discovery, registry resync, fingerprint mapping (§9.9), instance reconciliation, propagation — runs **async in the background** (in the task queue, §3) and surfaces *status* ("syncing" / "offline, showing last-known" / "up to date"), never a blocking splash. The app opens interactive on local/cached data and refines as sync lands.

### 5.3 Local-file mode vs. swarm mode

The agent operates in two scopes, and conflating them is what made §5.1's "always a node client" sound contradictory:

- **Local-file mode** — viewing/editing a *single* `.rehu` off disk. Needs **no node, no login, no swarm**. It just parses the self-describing file, shows/edits fields, renders the Markdown, reads/writes sibling screenshots. This is the "dumb viewer/editor" — and it's the correct behavior for a file the local node doesn't manage, a machine with no node installed, or a single `.rehu`+folder someone received.
- **Swarm mode** — the full catalog/admin experience. Node client, login, access-controlled, everything in §5.1.

**Local-file mode is the floor; swarm mode enriches when present.** Viewing/editing a local file is *not* an access-controlled operation — access control (§6.9) governs what a node serves over the network, and cannot govern a file the OS already lets the user read (the same "can't fight the device owner" logic as §6.10). So opening a local file requires no login at all. If the agent *does* have a session and recognizes the file's UUID as swarm-managed, it enriches the open view in place (per-user progress/notes, sync) — but enrichment lands as a non-blocking refinement (§5.2) and never delays the open. An edit made in local-file mode to a node-managed file is just a local write the node picks up via its change-notification/scan path (§9.5).

### 5.4 Single-instance behavior and file association

The agent uses the standard single-instance pattern: on launch (or `.rehu` double-click) it tries to bind a local socket; if it binds, it is the **main instance**; if the bind fails, another agent is already running, so it connects to that socket, forwards the file path, and exits — the main instance opens a new viewer view for the forwarded file. (This matches Qt's `QLocalServer`/single-application approach.)

- **One main instance hosts both scopes.** A forwarded double-click opens a local-file-mode view (§5.3, instant) regardless of whether the same instance also has a swarm-mode catalog window open. No separate viewer process.
- **Forwarded opens never block on login/sync.** The receiving instance opens the local file immediately and enriches only if it happens to be logged in and recognizes the UUID (§5.3).
- **Tray.** If tray mode is enabled, closing the window minimizes to tray and quit is explicit (tray menu / window menu); if disabled, closing quits. The tray lives on the **agent** (the only part with a GUI); quitting it does not stop the local **node** (§5.1).
- **Robustness:** if bind fails *and* connect also fails, assume a crashed holder left a stale socket — reclaim it and become the main instance. The socket name must be **scoped per OS user and per swarm**, so separate users or side-by-side swarms (§8) don't collide on one socket and forward to the wrong instance.
- **Platform mechanics live in §16.8.** How each OS delivers a double-clicked `.rehu` into the running instance — and the file-association and app-identity registration it needs — is OS-specific and is covered under packaging (§16.8).

## 6. Discovery, Swarm Identity, and Trust

### 6.1 Two separate questions

- **"Is this node even part of my network?"** → answered by **swarm identity**.
- **"Do I trust this specific node?"** → answered by **pairing/approval**.

These must be separate gates. Without the first, the second alone would let any installation of the same software (a neighbor's, a stranger's, even another household's identical setup) discover and attempt to pair with the user's nodes, since zeroconf advertises to anything listening.

### 6.2 Swarm ID

- Generated once, randomly, when the very first node is created ("create new swarm" vs. "join existing swarm" at first run).
- Carried in every zeroconf announcement. Nodes ignore announcements with a non-matching swarm ID outright — a foreign node never even becomes a pairing candidate.
- This also directly enables **running multiple independent swarms** on the same LAN (e.g. a real household swarm and a separate test/dev swarm), since they simply never see each other's traffic.

### 6.3 Discovery

**Zeroconf (mDNS/Bonjour)** for finding nodes on the LAN — the right tool for zero-config local discovery, and lightweight enough for the QNAP.

### 6.4 Node identity and pairing (Syncthing-style, trust-on-first-use)

Node identity follows the Syncthing model, which is cleaner than a separate pairing-secret scheme because the human-visible identity and the cryptographic identity are the *same object*:

- **A node's identity is the hash of its own self-signed TLS certificate's public key** (a "device ID"). The identity *is* the key — self-certifying, no certificate authority needed. All later traffic is mutual TLS in which each side verifies the other's presented cert hashes to the expected device ID.
- **Pairing is mutual approval of device IDs.** A new node announces (over zeroconf, gated by swarm ID §6.2) its device ID. The admin app shows the join request and its device ID; the user **independently verifies** it against the device ID shown on the node's own console/log (the side-channel check that defeats a rogue device claiming a fake identity — the same trust model as confirming an SSH host key). On approval, the node's device ID is recorded as trusted.
- Because identity is just the cert hash, there is **no separate long-lived secret to store or rotate** — the keypair *is* the standing credential, and "compare the fingerprint" reduces to "compare the device ID," with nothing else to get wrong.
- For headless boxes (QNAP), the device ID is surfaced the same way a fingerprint was: printed to console where there's a screen, written to a log readable over SSH as the guaranteed fallback, and echoed in the admin app's join request for side-channel comparison.

(This supersedes an earlier design that used a short-lived randomly-generated pairing secret exchanged for a long-lived credential. The cert-hash identity achieves the same trust-on-first-use property more simply, and the swarm-ID gate of §6.2 still sits in front of it.)

### 6.5 Membership model: hub-and-spoke, not full mesh

The **admin is the sole authority for swarm membership**. When the admin approves a new node:

- The admin records the new node's public identity in its registry.
- The admin **pushes the updated membership list to all other already-known nodes**, so every node trusts the new member without having to independently re-verify it.
- Any node only ever needs to trust one thing: the admin's say on who belongs. This avoids O(N²) pairing dances as the swarm grows, at a scale where a privileged admin role already exists naturally.
- A node that's offline when a new member joins picks up the update next time it reconnects.

This is the same pattern Syncthing calls an **introducer** — a trusted device that vouches for others to its peers — which independently validates the hub-and-spoke choice. The admin is the introducer; ordinary nodes trust the admin's vouching rather than re-verifying each new member themselves.

### 6.6 Registry home: preferred authority with chatter fallback (decided)

> [!NOTE]
> **Implement the registry-resolution and serve-after-resync logic (§6.6 + §6.10) with Opus, not the auto-switched Sonnet.** The startup sequence (preferred-authority → chatter-for-highest-version → last-known), the version-marker comparison, and the "serve only after catching up, unless nothing newer is reachable" gate have several edge cases (single node, cold start, partial power-up, vacation laptop) where a wrong default either deadlocks startup or serves stale access rules. Override to `/model opus` for both sections.

The propagated swarm registry (`.rehusw`, §4.8 — membership, users, hashes, access rules) and the instance registry (§10.2) are global state that isn't derivable from any single `.rehu`, so they need a defined place to resync *from*. The model is a **preferred authority with a chatter fallback**:

- A swarm may designate a **preferred authority** — the most reliably always-on box (e.g. the QNAP or the always-on Linux node). When reachable, it is the canonical resync source: a node that has caught up to it *knows* it is current.
- If **no preferred authority is defined**, or it is **unreachable**, or the node is **away from the swarm** (vacation laptop), nodes fall back to **chatter** — gossip with whatever peers are reachable, take the highest registry version-marker (§6.10), and serve on that. This is "current among who's reachable," accepting it may transiently lag until a higher-versioned holder appears.
- The **single node** is the degenerate case (§8.1): no peers, no authority needed — it is trivially current and serves immediately, never waiting on a discovery timeout.

So startup registry resolution is a simple sequence: **try the preferred authority → else chatter with reachable peers, take highest version → else serve last-known `.rehusw`.** Certainty when the authority is up; functional (if briefly-stale) when it isn't; no distributed consensus needed, because swarm config has a single writer (the admin, §6.5) and ordering is by version-marker, not agreement. The concrete lookup *sequence* above is the design; only its wire-level details are implementation.

### 6.6a Admin app portability

The agent must run identically on any machine — it holds no unique local state beyond a cached session token (§6.7):

- The **authoritative registry lives on the preferred authority node** (above), not on whichever machine the agent last ran on. The agent resolves and pulls the current registry on launch via the sequence above.
- The agent's user identity travels as a session token in the OS secure store (§6.7), not tied to one machine's disk.
- **Open question, still unresolved:** should the *admin* identity be a permanent "master key," or revocable/replaceable like an ordinary node identity, in case it's lost or compromised? (This is distinct from registry home, which is now decided.)

### 6.7 User authentication (distinct from node trust)

§6.1–6.6 authenticate *nodes* to each other. Authenticating *humans* is separate and necessary because any node can act as an HTTPS server a user logs into (including the thin tablet's server, §11.5):

- **Passwords are never stored, transmitted, or propagated — only salted slow-hashes are.** Each user record holds `hash = Argon2id(password + per-user salt)` (bcrypt/scrypt acceptable). A node authenticates a login by re-running the KDF on what the user typed and comparing. The plaintext password exists only momentarily at the login.
- **The user list (usernames + salted hashes + permissions) is shared swarm state**, propagated to every node the same way membership is (§6.5). Every node caches it because every node may be the server a user logs into — there is no central auth bottleneck, and offline login works on any node (e.g. the vacation laptop).
- **Accepted trade-off:** every node therefore holds all users' hashes, so a compromised node exposes them to offline cracking. At household scale (family + occasional lost laptop, not a determined adversary) this is acceptable, and it's bounded by the fact that **only nodes ever hold hashes, and visitors never become nodes** (§6.8).
- **The thin tablet logs in via a session** against whatever node serves it (which holds the hash and issues a session token/cookie). No credential is stored on the tablet.
- **The desktop agent caches a session token, never the password.** On login the serving node issues a session token (the same kind the tablet gets); the agent persists *that token* in the OS secure store (Keychain / Windows Credential Manager / Secret Service), so the user isn't re-prompted every launch. The plaintext password and any hash never touch the client. An expired or revoked token simply fails on next use and re-prompts — which is also how user-deletion/revocation reaches the agent, with no special-casing. Logout discards the token (and ideally invalidates it server-side). Login/logout are explicit menu actions in the agent.

### 6.8 Visitors and cross-swarm sharing (no federation)

A visitor is never allowed to join the swarm as a node. Two clean paths instead:

- **Guest account** — a normal user record (username + hash + view-only permissions), propagated like any user. The visitor logs into *your* node's web UI as a dumb browser client (same as the tablet); their device never becomes a node and never holds hashes or swarm state.
- **Export / import** — the way to share content with someone who has *their own* swarm. Copy resources to a disk, **stripped of swarm-bookkeeping**, and the visitor imports them into their own swarm. There is deliberately **no cross-swarm federation or trust** — that would be a large complexity tax for no household benefit; sharing is a deliberate, manual, identity-scrubbing copy.
  - An exported resource **keeps its UUID** (harmless, occasionally useful for later re-import/compare) but is **stripped of the version vector, activity log, per-user state, and instance-registry entries** — those are the originating swarm's private bookkeeping and would leak usage or corrupt ordering in the destination swarm. Export = resource content + `.rehu` metadata + screenshots, scrubbed of all swarm bookkeeping.

### 6.9 Access control

Access rules (which users may see which resources) are **swarm-wide config**, authored by the admin and propagated to every node exactly like membership (§6.5) and the user list (§6.7).

**Important separation from `.rehuco`.** Although it's tempting to put access rules in `.rehuco`, that file is deliberately *per-machine* (§9.3) — it holds mounts and ownership flags that legitimately differ box to box. Access rules, the user list, and hashes are the opposite: **swarm-identical, must be the same on every node**. So they do *not* ride in the per-machine `.rehuco`; they belong with the propagated swarm registry (the same data and propagation path as membership/users, §6.5–6.7), whether implemented as a registry section or a clearly-marked propagated sibling file. Putting machine-specific and swarm-identical data in one propagation bucket would force the system to either wrongly propagate mounts or wrongly fail to propagate grants. Concrete consequence: because grants propagate like membership, a node offline when a grant is made catches up on reconnect — so access is consistent regardless of which node a user logs into.

**Enforcement is server-side, at the serving node — never client-side.** Because the web client is a dumb browser (§11.5) and the Qt app is just a node client (§5.1), the only trustworthy filter is the node answering the request: it knows who the user is (authenticated session, §6.7), holds the propagated access rules, and **filters the catalog before sending anything back**. The user never receives a full list with disallowed items merely hidden in the UI — the node simply never returns what the user isn't entitled to. This is precisely why the user+access data must live on *every* node: each node enforces locally for whoever it serves.

**Grant types** (per §14): full access, per-resource, or by-tag. Tag-based grants are **evaluated dynamically at query time**, not expanded into a static list — if a user is granted "everything tagged `blender`" and a resource is later retagged, that resource automatically enters or leaves the user's view with no explicit grant edit. This is the one part of access that is *computed* rather than a static lookup, and it makes grant-by-category cheap and self-maintaining.

### 6.10 Serve-after-resync (startup gating on swarm info)

A node that was offline while users/permissions changed must not serve on stale access rules — it could grant access that was revoked, or deny access that was granted. So a node gates serving user-facing requests on first bringing its `.rehusw` (§4.8) up to date. The rule must be stated carefully, because taken literally ("don't serve until resynced with the rest of the swarm") it would make the swarm un-startable:

- **The vacation laptop** boots as the only node in reach — there is *no one* to resync with. An unconditional rule would mean it never serves, destroying the core offline use case.
- **Cold start at home** (e.g. after a power cut) boots every node at once; if each refuses to serve until it has resynced with the others — who are also all refusing — you get a startup deadlock or a fragile race.

So the correct rule is **"catch up to the most-current swarm-info source you can reach, then serve; if no more-current source is reachable, serve on last-known `.rehusw`":**

- On startup, the node attempts to resync `.rehusw` from the registry home (§6.6) or any reachable peer.
- If it reaches a **more-current** source, it must finish pulling the updated users/access **before** serving — the strict rule, intact, for the normal "briefly-offline node rejoins a running swarm" case.
- If it **cannot reach anyone**, it falls back to its durable last-known `.rehusw` and serves on that basis. For the vacation laptop this is correct and safe: it's *your* device, *your* account, on a network you control — the same LAN-local trust posture the whole design assumes — and refusing to serve would simply be useless.

**Deciding "more current" requires a version marker on `.rehusw`.** The admin is the sole writer of swarm config (§6.5), so a simple monotonic admin-side counter (or the same version-vector machinery as §7) suffices: a node compares its `.rehusw` version N against a reachable source's version M; if M > N, pull and apply before serving; otherwise serve immediately (so a node that missed nothing is never delayed). This makes the gate block *only* when there's genuinely something to catch up on.

**Resync source:** the place to resync *from* is resolved by the preferred-authority-with-chatter model (§6.6) — preferred authority if reachable, else chatter for the highest version, else last-known.

**Accepted limitation — offline revocation cannot reach a copy already in hand.** A consequence of allowing offline access: if you borrow a resource onto a laptop and go offline, and the admin then revokes your access or deletes your account, your laptop keeps serving that resource to you for as long as it never rejoins the swarm — and you could even export it (§6.8) out of the admin's reach. This is a *fundamental* property of any system permitting offline use, not a flaw specific to this design; the only "fixes" are time-bombed DRM-style local copies (fighting the device's own owner) or server-held decryption keys (which turn every offline access back into an online checkout, killing the offline use case). Both trade away the core capability the design exists to provide, to defend against a threat that barely exists at household scale — the "attacker" is a household member who already had legitimate access and kept a complete local copy. So this is a **deliberate, accepted boundary**: revocation is effective for future swarm access but cannot reach an already-held complete local copy; the design trusts swarm members, and defending against a member who kept a copy is an explicit non-goal. **Partial mitigation, free from §6.10:** revocation *does* take effect the instant that laptop rejoins the swarm (its `.rehusw` resync pulls the updated rules and it enforces from then on) — the hole is specifically a copy that *never reconnects*; any node that ever comes back online closes its own hole on next sync.

## 7. Sync & Conflict Resolution

> [!NOTE]
> **Implement this with Opus, not the auto-switched Sonnet.** The version-vector ordering, the concurrent-edit merge rules, the delete-vs-edit asymmetry, and the tombstone semantics are reasoning-dense — a subtle error here silently loses or resurrects data. Override `opusplan` to `/model opus` while implementing §7 even though it's "execution," and verify each merge case against the rules below.

Two different kinds of data live in `.rehu`, with different natural owners:

| Data | Examples | Owner | Conflict risk |
|---|---|---|---|
| Resource metadata | author, duration, description, screenshots | The node administering the files (per `.rehuco`, §9.3) | None — only one logical owner ever writes it; others hold cached, version-stamped copies |
| Per-user state | view progress, notes, bookmarks, borrow records, deletion/archival actions (logged, §7) | The user | Real, but narrow in scope |

**Resource metadata** never has a multi-writer conflict, by design — there's exactly one owning node per resource. Other nodes/clients show a cached copy, marked offline/stale if no live access route remains (§10). This also covers offline media (external drives, USB sticks, CD/DVD): the cached entry persists and is marked offline rather than disappearing.

**v1 scope decision — metadata is editable only when the resource is online; per-user notes/state are always editable.** To keep the single-writer guarantee above *actually true* rather than contradicted by offline-editing features (§11, §12), the first implementation deliberately forbids editing **resource metadata** (including screenshots, §4.6) while the authoritative copy is unreachable. What remains editable offline is **per-user state** — notes, progress, bookmarks, borrow records — which is single-user and merges cleanly. This removes the hardest distributed problem (two divergent offline edits to shared metadata) from v1 entirely, with no loss of the actually-valuable offline capability (taking notes on vacation). See §12 for how this narrows the writable-cache concept.

**Future hook, not built in v1:** offline metadata editing *may* be enabled later, gated behind a merge/diff tool (text-diff for metadata fields, old/new side-by-side comparison for screenshots — both straightforward library work, deferred only because the UI doesn't pay off until offline metadata editing exists). To keep that path open cheaply, **metadata carries `resource_version` markers from day one even though v1 never has to act on a metadata conflict** — so a future merge tool has the version history it needs. Build the storage for future merge now (free); defer the merge UI (not free).

**Per-user state** can genuinely conflict, but in a bounded way — never general multi-node consensus. Ordering is determined by a **version vector**, not by wall-clock time:

- **Version vector (ordering, never pruned).** Each resource carries a small per-node-counter vector — `{nodeA: 5, nodeB: 3, …}`. A node bumps its own counter on each action it makes. "Newer" means "dominates component-wise"; if neither of two vectors dominates, the change is genuinely **concurrent** and must be reconciled. This is clock-independent (immune to the skew across Win/Linux/Mac/QNAP), and it is deliberately *lighter than git* (no content-addressed DAG/merkle tree) and *far lighter than a crypto ledger* (no signing chain — tamper-evidence isn't needed in a trusted household swarm). The vector is tiny (one integer per node that ever participated) and is **never pruned** — dropping a node's counter would reintroduce ordering ambiguity and resurrection-style bugs.
- **Activity log (human-readable history, prunable).** Separately, each resource carries an append-only log of meaningful events — "user B archived this on date X (reason: low quality)," "user A resurrected from local copy on date Y" — modelled on a GitLab issue's Activity feed. This is what makes conflict-resolution UIs intelligible to a human (the version vector only says *that* something diverged; the log says *what and why*). Because it can grow unbounded, the log **is** the prunable structure: a configurable function/setting can drop entries older than X or keep at most the last Y. Pruning the log never affects ordering (that lives in the vector). **Exception:** pruning never removes the current state-defining event (the most recent delete/archive/resurrect), only superseded historical ones.

Reconciliation rules over this model:

- **Newest action wins, by vector comparison.** If one side's vector dominates, it wins outright (the common case — e.g. you edited a note on the laptop, nothing changed at home). If neither dominates (true concurrency), fall to field-level merge below.
- **Field-level merge for concurrent edits** (no user prompt needed): watched segments (union), bookmarks (union by position), viewed flags (logical OR). Free-text notes (and edited screenshots, if offline metadata editing is ever enabled, §7 future hook) are the fields that can genuinely collide; worst case, keep both and surface for the user. Data is never silently lost.
- **Deletion, archival, and resurrection are ordinary logged actions in this same model** — not a separate mechanism. A deletion's "tombstone" is simply the delete event's position in the version vector: a node offline during the delete sees, on reconnect, that the delete vector dominates its last-known state and applies it; a rescan that re-finds the on-disk `.rehu` does *not* resurrect it, because the tombstone vector dominates the file's last-known edit vector. This closes the resurrection bug without any special-casing.
- **Asymmetric stakes for delete-vs-edit (the one nicety).** Edit-vs-edit losing the older edit is acceptable. But a delete silently winning over a concurrent edit (losing someone's work), or an edit silently resurrecting something deliberately deleted, are bad surprises — so a delete that is *concurrent with* an edit does not auto-apply; it surfaces in the duplicate-review-style verdict queue (§10.5) for a human decision. Plain delete-vs-delete needs nothing (both agree).
- This reconciliation is **not limited to a single two-party case** (home vs. one checkout). It generalizes to any number of independent edit sources reconciling one after another — each event merges against whatever the current state is at that moment (§12).
- **Multiple edits during one continuous offline period are not a conflict among themselves** — they're sequential against one evolving local state, coalesced into a single outgoing sync on reconnect (§9.5).
- **Active playback progress** is pushed frequently (periodically during playback, and on graceful stop), so switching the serving node or reconnecting a previously-used one reflects state at most seconds stale, not a whole session behind (§9.6).

## 8. Multiplicity: Swarms and Nodes per Machine

- **One swarm per node process, always.** A node's identity, config, and data directory are scoped to exactly one swarm. This keeps every piece of state (registry, keys, cached catalog) free of an extra "which swarm" dimension that would otherwise have to thread through everything.
- **Multiple node processes per machine** are fully supported and require no special design — each is just an ordinary node with its own config/data directory, own identity, own port, and own zeroconf service name (to avoid mDNS collisions). This covers both "two swarms on one box" and any future case of separating folder groups onto distinct processes.
- **Folder-group separation within a single swarm does not need separate node processes.** A single node can watch/serve multiple folder roots as plain configuration. Splitting into separate processes is only justified by independent restart/update needs, materially different storage reliability per folder set, or future performance scaling — none of which apply today.

### 8.1 The single node is the base case, not a special case

Every swarm is single-node at birth (creating a swarm = minting a swarm ID, §6.2, with no peers yet), and a swarm may **legitimately stay single-node forever** — someone who just wants the app on one box. This is a first-class supported mode, not a degraded form of multi-node:

- **A lone node is its own registry authority.** The registry-home model (§6.6) degenerates cleanly to one node: *this* node holds the swarm registry, users, access rules, and instance registry, and the resolution sequence short-circuits (no preferred authority needed, no peers to chatter with). The agent must not hunt the network for an authority and hang when there isn't one.
- **A lone node serves immediately and confidently.** The serve-after-resync gate (§6.10) must treat "I am the registry authority" as instantly satisfied, *not* as "I failed to reach peers, falling back." Same outcome, but a one-node install must never pause on a discovery timeout waiting for peers that will never answer — that would be a bug born of treating single-node as degraded multi-node.
- **Create-swarm and single-node-forever are the same path.** "Single-node forever" is just "created a swarm and never invited anyone." Multi-node is the *elaboration*; the base case is one fully-functional node that serves, authenticates, and enforces access entirely on its own.

## 9. Mounts, `.rehuco`, and Cross-Box Visibility

### 9.1 The problem

A machine running the Qt app (or a node) may have network shares from *other* boxes mounted locally — e.g. the Mac mini has the QNAP's share mounted. The same physical files can then be reachable two ways at once: directly via the mount, and via the QNAP's own node over REST. Naively, this risks the same resource appearing as two separate catalog entries.

### 9.2 Resolved by UUID, not by path-guessing

Path-based inference (trying to guess that a given mount root corresponds to a given node's share) is fragile — mount points are named arbitrarily and have no necessary relation to a node's internal paths. Instead: **a resource discovered via a mount and the same resource reported by a node are recognized as identical purely because their `.rehu` UUIDs match.** Once matched, the catalog holds one logical entry with multiple known **access routes** (mount path, node REST endpoint, or both), and can prefer whichever route is fastest for a given operation (typically: local mount > delegating to a node over the network).

This same model generalizes cleanly: **more than one node can serve the same resource**, if more than one box happens to have the owning box's share mounted. This isn't a conflict — it's just additional access routes for the same UUID. If the originally-owning box goes down but another node still has it mounted, that node can keep serving the resource live; the read-only cached fallback (§10) only applies when **no** live route remains at all.

### 9.3 `.rehuco`: explicit, local, declared scope

Rather than relying purely on empirical UUID-matching to discover the mount-to-node relationship (which only self-corrects after both sides have independently reported the same UUID at least once), the system uses a **`.rehuco` file, local to each machine**, that explicitly declares:

- which folder roots this machine/app should scan or track
- for mounted roots, which node administers that content and how to reach it
- which plugins (§13) should be loaded for this machine

`.rehuco` is **per-machine, not swarm-wide** — mounts inherently differ machine to machine (different mount points, different machines even having a given share mounted at all), so a shared/central `.rehuco` wouldn't reflect any single machine's reality. This also removes any cold-start ambiguity: the mount-to-node relationship is known immediately at startup, not discovered after the fact.

**Do not put swarm-identical data in `.rehuco`.** Users, hashes, and access rules are swarm-wide and must be identical on every node; they belong with the propagated swarm registry (§6.7, §6.9), *not* in this per-machine file. The dividing line: `.rehuco` holds what is legitimately *different* per box (mounts, ownership flags, retention opt-ins, auth-trusted flag, plugins); the propagated registry holds what must be *the same* everywhere (membership, users, access rules).

### 9.4 Nodes can also serve mounted (not locally-owned) content

The same mounting capability applies to nodes, not just the Qt app — a node can serve a resource it only has access to via a mount from another box, using the same `.rehuco`-declared relationship.

### 9.5 Editing through a mount: explicit change notification, not disk-watching

Because most editing happens in the Qt app, and the Qt app may often be editing a `.rehu` via a mount rather than by talking to the owning node, the node responsible for that content needs to learn about the change quickly — without requiring a continuously-running filesystem watcher on the node (an unwanted resource cost, especially on the QNAP). Instead:

1. The Qt app edits the file directly through the mount (fast, no round-trip needed for the write itself).
2. Knowing — via `.rehuco` — which node administers that path, the Qt app sends a lightweight **"re-read this specific resource"** notification, keyed by UUID/path.
3. The node re-reads just that file and updates its cache, then propagates the change onward through the swarm as it would for any other metadata update.
4. If the node is unreachable at that moment, the notification is queued as a retryable task (§3) rather than lost — it is not the Qt app's job to keep retrying by hand, and it is not the node's job to discover the change via a future full rescan (though scanning remains how a node discovers changes it wasn't explicitly told about, e.g. files dropped in by some other means).
5. A burst of rapid edits to the same resource should be debounced into a single outgoing notification, consistent with the coalescing rule in §7.

### 9.6 Node handoff during active viewing

A user may start watching a tutorial via the node on their PC, then switch to the node on the TS-230 (e.g. because they're shutting the PC down), and later reconnect the PC — expecting playback progress to follow seamlessly throughout. This requires no new mechanism beyond §7's per-user state sync, but does require a **higher push frequency during active playback**: progress should be written to the authoritative record every few seconds (or on pause/seek/stop), not only at session end, so that switching the serving node — or reconnecting one used earlier — reflects state that's only seconds stale rather than a full session behind. A node taking over playback reads current state before resuming, the same read any node would perform on session start.

### 9.7 Example deployment: multiple machines mounting one share

The same share can legitimately be mounted by several machines at once (e.g. the PC, the main desktop, the Mac mini, and a low-power always-on Linux box could all mount the QNAP's export) — this is an ordinary network-share capability, not something the architecture needs to specially support. What it means in practice is that **"who serves a resource" doesn't need a single designated answer**; per §9.2, any subset of machines with access can each run a node for it simultaneously, with no conflict. This makes per-machine role assignment a matter of matching each box's power/compute profile to a job, rather than picking one "correct" server:

- A weak-but-already-always-on box (e.g. one already running other always-on services, with idle CPU/RAM to spare) is well-suited to **light, always-available serving** — answering catalog queries, serving cached metadata/thumbnails, proxying file reads — but should be explicitly excluded from CPU-heavy tasks (checksumming, scanning, dedup matching), which belong on whichever machine is being actively used at the time and has real headroom.
- The box that actually owns the disks (e.g. the QNAP) doesn't strictly need to run its own node at all if another always-on machine adequately covers the serving role via a mount — though running one anyway adds redundancy if its power/compute cost is acceptable.
- This role assignment is a deployment/configuration choice (expressed via `.rehuco` and task-dispatch tagging, §4.5), not an architectural constraint — different households, or the same household at different times, could assign roles differently without any design change.

### 9.8 Configurable durable retention of remote/offline metadata

`.rehuco` can opt in, per source, to keeping a **durable local copy of that source's `.rehu` metadata and screenshots** — for usually-offline media (external drives, USB sticks, CD/DVD) and optionally for other nodes. Rationale and rules:

- **Why**: offline media are painful to rescan one-by-one, and a powered-off node's content would otherwise drop out of the catalog. Retaining their metadata locally keeps them browsable while disconnected, and — because the retained copies are ordinary local files — keeps them present across a full cache rebuild (§2). Extending the same option to other nodes' metadata is for completeness/flexibility, not necessity.
- **It's opt-in and configurable** because every retained copy is, by definition, a cache that can go stale relative to its true owner. The cost of the convenience is more staleness surfaces; the mitigation is cheap version-marker staleness detection (§4.7), not frequent rebuilds.
- **Retained copies are read-only stand-ins.** They reflect the v1 rule (§7): you can browse them offline and attach your own per-user notes, but you cannot edit the *resource metadata* of a retained copy until its real owner is reachable. (For genuinely write-once sources like sealed CD/DVD, the metadata is never editable on the source at all; edits live on a separate mutable instance, §10.1.)
- **Staleness is resolved by version comparison, not blind overwrite.** When a retained source becomes reachable, compare the stored `resource_version`/timestamp against the live one; re-pull only if it moved.

### 9.9 Self-mapping via fingerprint files

UUID-matching (§9.2) resolves overlaps *per resource, reactively*. Fingerprinting resolves the **topology of shared storage proactively** — it discovers that nodeA's `foo/1` + `foo/2` and nodeB's mounted `foo/` are the same underlying storage, and how their paths map, without waiting to observe per-resource UUID collisions. Mechanism:

1. Each node drops a **content-unique fingerprint file** (containing a UUID identifying that node-root) into each top-level root declared in its `.rehuco`.
2. All nodes do a fast, shallow scan looking for *other nodes'* fingerprint files.
3. If nodeB finds nodeA's fingerprint inside what nodeB calls `foo/`, then nodeB's `foo/` and nodeA's root are the same storage, and the **relative paths reveal the mapping** (nodeA's `foo/1` = nodeB's `foo/1` under the shared root). This reconstructs cross-node path-mapping automatically, including asymmetric cases (A maps two subdirs separately; B mounts the parent whole).

Requirements: the fingerprint file must be content-unique per node-root (UUID inside), and the scan must handle **multiple fingerprints in one tree** (B's `foo/` may contain A's *and* C's fingerprints if three boxes share it). This same map is what detects the double-primary misconfiguration (§9.10): if two nodes both claim primary for storage the fingerprints prove is shared, the swarm flags it.

### 9.10 Folder-add: declaring primary/local vs. remote/mounted ownership

When the admin adds a folder root to a node (via that node's `.rehuco`, edited through the node per §5.1), it must be tagged as one of:

- **Primary/local** — this node owns the files and is the authoritative metadata writer (§7).
- **Remote/mounted** — this node serves files it reaches via a mount but does *not* own them; some other node is primary.

This flag is the concrete source of truth for §7's single-writer guarantee. **Hard constraint: exactly one node may be primary for any given storage.** Two nodes both marking the same (fingerprint-proven shared) storage as primary is a misconfiguration that breaks the single-writer guarantee; the self-mapping function (§9.9) is what detects and flags this.

### 9.11 Node benchmarking and grading

An explicit, user-triggered task (§3) that produces per-node performance grades to feed the dispatch decisions in §4.5/§9.7 (currently described only qualitatively as "the fast box" / "the weak box"):

- Create a large test file, generate its checksum, then **clear the OS disk cache and re-checksum to measure cold-read speed** (not warm-cache speed).
- Assemble per-node numbers (cold read throughput, checksum throughput, etc.) into a **grade** the dispatcher uses as a score.

Caveat to record: dropping disk caches is disruptive and **platform-specific** (mechanism differs across Linux/macOS/QNAP and may need privileges). The benchmark must therefore be occasional and explicit, never automatic, and must **degrade gracefully** where cold-cache measurement isn't permitted (fall back to warm-cache numbers, flagged as such).

### 9.12 Self-determined fastest/safest move/rename

> [!NOTE]
> **Implement the cross-filesystem move with Opus, not the auto-switched Sonnet.** The copy → verify-checksum-on-target → delete-source-only-if-verified sequence (and keeping the source's instance-registry entry until verification passes) is data-loss-sensitive: a wrong ordering or a skipped verification can delete the only good copy. Override to `/model opus` for the cross-FS path.

The system chooses *how* to perform a move/rename rather than assuming:

- A rename/move **within one filesystem** is a near-instant metadata operation — but only when performed by something with **direct local access to that filesystem**. The fingerprint map (§9.9) identifies which node is local to the files' storage; the move is **delegated to that node**, which does the instant in-place rename.
- The same rename issued **over SMB from a remote mount** may not be recognized as in-place and can silently degrade into copy-then-delete (slow, briefly doubles disk use). The design routes *around* needing to predict Samba's behavior: same-FS moves are delegated to a local node; anything else is treated as a cross-filesystem move.
- **Cross-filesystem moves are checksum-gated (hard rule):** copy → generate/verify checksum on the *target* (preferably by the node local to the target FS) → delete the source **only if verification passes**. The source retains its instance-registry entry (§10.2) until target verification succeeds, so an interrupted move is always recoverable and never loses data.

## 10. Identity, Instance Tracking, and Deduplication

### 10.1 UUID identifies lineage, not "the one legitimate copy"

A single resource's UUID can legitimately exist in **many physical locations at once**, by design — a backup, a vacation checkout, and the live copy on a node are all valid, simultaneous instances of the same resource. UUID is not "uniqueness enforcement"; it answers **"are these the same resource?"**, enabling:

- **Corruption recovery**: if a primary copy fails checksum verification, any other known instance with the same UUID (a backup on an offline HDD, a USB checkout) is a candidate to restore from, verified against the checksum manifest before being promoted.
- **Manual backups**: the user keeps the TS-230's two drives unmirrored and does manual rsync backups onto smaller, mostly-offline HDDs. These backups intentionally share UUIDs with their originals.
- **Read-only/sealed media (CD/DVD)**: once burned, a disc's own `.rehu` is frozen by definition — it can never be reconciled back onto. The disc is treated as one more instance of the UUID, tagged read-only/sealed: useful for provenance and as a restore source, but never a sync target. All future edits (notes, tags, fixed typos) live on a separate, ordinary, mutable instance elsewhere in the swarm, linked by the same UUID — the same separation already used for online-only resources, where the `.rehu` is independent of the (uncontrollable) URL it describes.

### 10.2 Instance registry

Each UUID maps to a set of known **instances**, each tagged with a role (primary, backup, checkout, mounted-elsewhere, sealed/read-only) and a health/last-seen state. Reconciliation and dedup-recovery logic operate over this registry — e.g. skipping sealed instances when looking for a sync target, or surfacing a healthy backup when the primary fails a checksum check.

### 10.3 Failure model, precisely

"A node is down" and "the underlying files are unreachable" are **independent conditions**, not the same event:

- If a node is down but the files remain reachable via some mount (by the Qt app or by another node), the resource stays fully live and editable through that other route — no fallback needed.
- The read-only/writable-cache fallback (§12) applies only when **no live access route remains at all** for that resource — true offline media being the common case (a USB stick or disc that's physically disconnected most of the time), not merely "the node that happens to administer it is off."

### 10.4 Deduplication

UUID matching alone is not sufficient for dedup, because two `.rehu` files can describe the same real-world resource without sharing lineage — e.g. a copy received from someone else who generated their own `.rehu` independently, or multiple accidental downloads of the same thing made before cataloguing existed. Dedup needs a **separate, complementary signal set**:

- **Content checksums** (strongest signal, when files are present to compare)
- **URL matching** (useful, but uneven in reliability — see below)
- **Fuzzy matching** on title/author/size when neither of the above is available

**URL specificity must be tracked explicitly.** Some `.rehu` entries carry a real, unique URL (a specific product/course page); others, where the original page no longer exists, were backfilled with a generic publisher homepage as a placeholder. These look identical as plain strings but mean very different things for matching — treating them the same would cause false-positive dedup matches concentrated exactly on resources whose metadata is already weaker. The schema should mark generic/fallback URLs explicitly (e.g. a flag, or a separate field from a confirmed specific source URL) so dedup logic can exclude them from the match signal rather than being misled by them.

### 10.5 Duplicate review UI

Automated matching only ever **proposes**; a human verdict is recorded and never re-asked:

1. **Confirmed duplicate, keep one** — user picks the canonical copy; the other(s) are marked appropriately (e.g. tracked as a known extra copy, consistent with not silently losing track of removed items) rather than deleted with no record.
2. **Confirmed duplicate, keep both** — e.g. different rips/quality. Lineage converges (shared UUID, or an explicit duplicate-link) while both physical instances persist in the instance registry (§10.2) — the same mechanism as backups, just discovered after the fact.
3. **Not a duplicate** — the specific pairing is recorded as rejected and must never be re-proposed, so re-scans don't repeatedly resurface the same false positive.

Each verdict is permanent until explicitly revisited, mirroring the system's broader principle of not re-asking questions the user already answered (e.g. not re-suggesting a deleted/rejected resource for re-download).

**Open question**: when two duplicates merge (case 1), what happens to per-user state if both copies had independently accumulated some (e.g. partial viewing progress on each)? The same union/merge rules from §7 likely apply, but this should be a deliberate decision when dedup is designed in detail, not an assumption.

## 11. Borrowing, Library-Shelf Storage, and Scheduled Archival

### 11.1 The "library shelf" pattern

A box holding original content (e.g. the QNAP) can be treated as a library shelf that's normally **closed** — deliberately powered fully off, not just idle, to save power/wear — with content **borrowed** onto an always-on machine when the user wants it reachable, and the shelf reopened (powered on) only when needed again. This is a distinct, deliberate workflow, different in kind from both:

- a **checkout** (§7) — leaving home with a copy, syncing back later — and
- the **implicit offline cache** (§12) — content becoming unreachable unexpectedly.

Borrowing is planned and user-triggered, may last an arbitrary length of time (not bounded by a trip), and its motivation is specifically to allow the source box to be powered fully down rather than idling.

### 11.2 Mechanism: another instance role, not a new system

A borrowed copy is just another entry in the instance registry (§10.2), tagged with a role such as `local-borrow`, alongside `primary`, `backup`, `checkout`, `mounted-elsewhere`, `sealed`. It's created the same way a checkout is (verified copy, snapshotted base state) and reconciles back using the same rules (§7) once the source becomes reachable again — "the QNAP was off for a while" is functionally identical to "a checkout was offline for a while" from the reconciliation engine's point of view. While borrowed, the local copy is a fully live, fully-featured instance (not a degraded cache) for as long as it exists, regardless of how long the source stays powered off (§10.3).

Two things worth deciding deliberately when this is built (not resolved here):

- Whether powering the source down/up is manual or automated (e.g. a scheduled shutdown after a period of no active node traffic, with Wake-on-LAN to bring it back on demand).
- Borrowing is inherently per-resource and selective — worth treating as a deliberate user action ("borrow this") rather than something that could be confused with bulk replication of the whole library.

### 11.3 Scheduled archival of a borrowed resource

The user can mark a borrowed resource **to be archived on return**: rather than simply deleting the local borrowed copy, the goal is to shrink the *original* (or whichever instance becomes the long-term one) by removing large video files, while deliberately keeping `.rehu` metadata, the `infoXX.*` images, and other explicitly-preserved extras (e.g. code-example zips). This is a structural change to what the resource contains, not a lifecycle/visibility change like the tagging or duplicate-review mechanisms elsewhere in this doc — though it's recorded using the existing tagging mechanism (§4.1) rather than a new schema field. A few consequences worth tracking precisely:

- **"Archived" is a tag, not a new schema state.** It's applied to the resource using the same general-purpose tagging mechanism already used elsewhere (§4.1), not a dedicated field or enum value.
- **`complete` is never touched, before or after archival.** Per §4.1, `complete` reflects whether all expected files were present *at cataloguing time* and is not revisited afterward for any reason — archiving (or any other later, deliberate file removal) does not flip it, set it, or otherwise interact with it. It is write-once-at-creation, full stop.
- **Two archival granularities.** The user can choose to archive **everything** (keep only `.rehu` and images, remove all video) or **selectively** (keep a chosen subset of files in addition to `.rehu`/images — e.g. one or two representative/interesting videos), so archival is not strictly all-or-nothing on the video content.
- **Execution is deferred until a live route exists.** Archival is scheduled as a task (§3) that stays pending — the same way a node-change-notification waits when its target is unreachable (§9.5) — and executes the moment the source (or any node/route with the resource mapped) becomes reachable again, i.e. when the "shelf" is reopened.
- **The checksum manifest is purged, not flagged.** Once a file is removed by archival, its entry is deleted outright from the checksum manifest, rather than retained with an "intentionally removed" marker — the manifest should only ever describe files that are actually still present.
- **Archiving the original does not affect the borrowed copy's lifecycle.** The two are decoupled: marking/executing archival on the original does not automatically delete the local borrowed copy. The borrowed copy's own removal (or continued retention) remains a separate decision for the user to make independently.
- **The action is effectively irreversible** for the files it removes — once gone, they're recoverable only from a backup instance (§10.2) if one exists, not from the archived resource itself.

### 11.4 Recording borrows in the user's meta block

A borrow is recorded as an entry in the **user's meta block inside the resource's own `.rehu`**, rather than only in a separate registry. This makes a borrow self-describing and self-cleaning, consistent with the rest of the design:

- **Multiple simultaneous borrows are a list, not a flag** — `(device id, borrowed-at, optional expected-return)` per entry — so the same resource can be borrowed onto more than one *node-capable* device at once (e.g. a laptop and a desktop), each tracked independently. Note: a borrow target must be able to run a local node and hold the copy; the iOS tablet cannot be a borrow target (§11.5).
- **An explicit "return" step removes that device's entry.** Borrow is declared, return is declared; the absence of an entry means not-borrowed. No heuristic inference of borrow state.
- **Because the borrow record lives in the resource's `.rehu`, it survives a cache rebuild** wherever that `.rehu` is reachable or retained (§2) — unlike a purely transient instance.

Two caveats, since they're this approach's failure modes:

- **A borrow taken while the source is offline can't be written into the source's `.rehu` immediately** — which is the normal library-shelf case (§11.1), where the owner is deliberately powered off. The borrow is recorded locally on the borrowing device and synced into the resource's meta when the owner next comes up, subject to the same deferred eventual-consistency rules as any other per-user-state edit (§7/§12). A borrow record is per-user state, not instantaneous global truth.
- **Stranded borrow entries need a visible manual cleanup path.** A lost/wiped device that never performs "return" would otherwise leave its entry lingering forever. At household scale, a manual "clear this borrow" in the admin/editor UI suffices (no auto-expiry needed), but the UI must surface borrow entries so a stranded one is visible and removable. An optional expected-return date lets the UI flag an overdue borrow without auto-removing it.

**Mental model — OneDrive Files On-Demand.** The borrow/normal/archived-stub states map cleanly onto OneDrive's three states: archived-stub (metadata + screenshots only, §11.3) ≈ online-only placeholder; a normal node-resident copy ≈ locally available; a borrow ≈ pinned/"always keep on this device." The analogy is good for vocabulary but breaks on consistency: OneDrive has a single always-available cloud authority behind all three states, whereas this system's authority is distributed and sometimes deliberately powered off — so the *states* transfer but the *sync-back/reconcile* model (§7) does not.

### 11.5 Thin tablet and the vacation topology

The iOS tablet is a **pure thin web client** — deliberately, because no native app will be published for it. This has firm consequences:

- **The tablet can never hold a borrow or any per-user offline state.** It has no local node and no local resource storage; it only ever *views* what a reachable node serves over HTTPS. ("Borrow onto the tablet" is therefore not possible — corrected from an earlier example.)
- **Away from home, the laptop's own node is the tablet's server.** The canonical vacation topology: the laptop runs a node that holds the borrowed resources *and* serves the web UI over HTTPS to the tablet, reached over LAN or the laptop's hotspot. This means the **laptop node must run the web-server role**, not just the desktop Qt app.
- This reinforces the off-LAN boundary (§17.2): there is no "tablet reaches home over the internet" path. The tablet always talks to a *local* node — a household always-on box at home, or the laptop while away.

### 11.6 Resolving a borrow when the resource was deleted or archived meanwhile

While user A has a resource borrowed, user B may delete it (everything, including metadata) or archive it (keeping only metadata, screenshots, and explicitly-selected files) back in the swarm. Because **A's borrowed copy is a complete, valid instance (§10.2)**, B's action is never destructive to A — it's a divergence to resolve on A's return, with A's copy available as a recovery source. The version vector (§7) detects the divergence; the activity log (§7) tells A *what B did and why*.

On A's return, A is offered three choices in both cases:

- **Drop** — A agrees with B; A's local copy is discarded too.
- **Archive from local** — keep metadata/screenshots/selected files using A's copy.
- **Resurrect from local** — A overrides B's opinion; A's complete copy is promoted back. Resurrection is itself a logged action with a new vector position that dominates B's delete, so when B's node next syncs it sees "resurrected, newer than my delete" and the resource correctly returns on B's side too, with the log explaining why.

The difference between the two cases:

- **B fully deleted:** the swarm has nothing; the three choices operate purely on A's copy.
- **B archived:** the swarm has the stub; "resurrect/archive from local" **merges** A's fuller copy with what B kept — A's copy contributes the files B dropped, the stub contributes any metadata edits B made meanwhile.

**B's deletion reason is always preserved and surfaced to A** (carried in the activity log), so A sees *why* B removed it before deciding — and may come around to agreeing with B later. This is the same "never silently lose a human's reasoning" principle as the deletion-with-memory feature (§10.5).

## 12. Offline Editing Without a Deliberate Checkout

Distinct from a deliberate vacation/USB checkout (§7) or a deliberate borrow (§11): a resource's owning storage can become wholly unreachable (the whole box goes down, not just its node process) with **no prior checkout having been made**. In this case, the cached entry should remain **editable for per-user state** while disconnected.

**v1 scope (per §7):** the writable-cache here is a *per-user-state-writable* cache, **not** a fully-writable one. While the resource is unreachable, the user can still edit their own notes/progress/bookmarks/borrow records, but **resource metadata and screenshots (§4.6) are read-only** until the authoritative copy is reachable again. This deliberately narrows the earlier framing ("remain editable, including its images"): in v1, images-as-screenshots are part of resource metadata and are *not* offline-editable; only per-user state is. This is what makes §7's single-writer metadata guarantee hold without a merge tool.

The per-user-state edits accumulate locally against the last-known base and reconcile using the same rules as any other case once the resource is reachable — generalized, per §7, to handle more than one independent edit source reconciling in sequence (e.g. two different boxes each editing their own per-user state while the source was down, reconciling one after the other once it returns — the second reconciliation merges against a state that already includes the first).

If offline metadata editing is enabled in a future version (§7's future hook), *that* is when the merge/diff tool and the multi-writer metadata reconciliation become necessary — they are explicitly out of scope for v1 precisely because v1 forbids the edits that would require them.

## 13. Plugins

Resource types (tutorial, reference images, Daz3D, and future types) are implemented as **plugins**, loaded per `.rehuco` declaration (§9.3). The core app provides default plugins for tutorials, reference images, and Daz3D, but the architecture doesn't assume these are exhaustive.

### 13.1 Split between core and plugin-owned responsibility

| Core (same for every resource type) | Plugin-owned (varies per type) |
|---|---|
| UUID, instance tracking, checksums, swarm sync | Schema extension — custom fields beyond the common set (§4.1) |
| Tasks/job queue, node communication, REST plumbing | Viewer layout and behavior |
| Permissions/access grants | Editor layout and behavior |
| Dedup detection mechanics | Web rendering and interaction |
| `.rehuco` parsing and plugin loading | Custom actions with their own side effects (e.g. Daz3D install/uninstall) |
| The **field toolkit** (a shared library of reusable field widgets: text, switch, tag-list, date, rating, duration, size, choice, path, image-count, unknown, …) that plugins compose from | Browser columns + cover/shelf rendering for this type (§13.1c) |
| The **generic resource browser** (common columns) and the **viewer dock** shell | Search/index contributions (e.g. per-image tag search) |

A resource whose plugin isn't installed/loaded on a given machine should still degrade gracefully — at minimum showing the common fields — rather than failing outright, since `.rehuco` (and therefore plugin availability) is per-machine.

**Plugins span a spectrum from declarative to code.** Two earlier ideas — a code-plugin model, and a TutCatalog5 experiment where `.rehuco` *declared* each type's fields from a fixed toolkit — are unified by layering rather than choosing:

- **Declarative type** — a type defined purely as a *field list* over the shared field toolkit (text/switch/tag/date/rating/…), no code. Cheap to add (config, not programming), safe (zero code execution), but limited to what the toolkit offers. Good for simple types (e.g. a basic "3D object" with title/tags/format).
- **Code plugin** — a type that uses the same toolkit fields *plus* its own custom widgets and actions (the Daz3D install action, refimages redaction overlays, the sketch slideshow). Maximally flexible; the only thing that needs real code.

Both produce the same on-disk block (§13.1a) — whether a block's fields came from a declaration or from plugin code is purely a rendering detail. This also answers a trust question (§17.2): **declarative types carry no code-execution risk; only code-plugins are a trust/distribution surface.** "Add a simple new resource type" is a config task; code is needed only for behavior beyond the toolkit.

### 13.1a Plugin blocks: keyed, versioned, single-live-type

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

### 13.1b Generic fallback editor for inert / unknown blocks

Inert blocks (and a live block whose plugin isn't installed here) are shown via a generic fallback rather than failing:

- **Unknown block** (whole plugin not the live type, or not installed): a labeled, collapsible section marked with *why* it's flagged — "not the current type" vs. "plugin not installed here" are different situations the user resolves differently. Default is carry-verbatim, with an explicit drop option.
- **Unknown field inside a known live block** (e.g. the installed plugin is an older version than the file's block): per-field UI to **map to a known field, drop, or carry verbatim** — most useful here because the plugin *is* present and the user may know where a stray field belongs. Unmapped, undropped fields are carried untouched.
- Flagged items **stand out in the viewer**, labeled by provenance (newer-version-of-installed-plugin vs. plugin-absent vs. not-the-current-type) so the user knows whether the fix is "upgrade the plugin," "install it," or "this is just inert payload."

### 13.1c Resource browsers (per-type, with shelf/table modes)

The catalog is presented through **browsers**, which are the catalog-level counterpart to the plugin block model (§13.1a): just as a `.rehu` has common fields plus a type-specific block, a browser has common columns plus type-specific columns.

- **Generic resource browser** — a table of *all* resources, columns = common fields (title, publisher, url, size, change date). The type-agnostic baseline, and the fallback for any type whose plugin isn't installed (mirroring the generic field-editor fallback, §13.1b).
- **Per-type browsers** — extend the generic browser with **plugin-contributed type-specific columns**: tutorials add duration / view-progress; reference-images adds image-count; etc. Contributing browser columns (and cover rendering) is a plugin responsibility (§13.1).
- **Two display modes** — tabular, or **cover/shelf view** (Calibre-style), per browser.
- **Clicking a resource opens its viewer dock** (§5.3).
- **Click-to-filter** (restored from TutCatalog4): tags, author, and publisher render as links in the viewer; clicking one sets the corresponding filter on the active browser (clicking an author shows all that author's resources, etc.). This couples the viewer dock to the browser's filter state — natural under the dockable-UI model — and was the primary filtering affordance in the usable older version.

### 13.2 Tutorial plugin

- **Viewer** (triggered by double-clicking `.rehu` in File Explorer): read-only field display; rendered Markdown description; horizontal image strip with click-to-maximize, prev/next navigation, hideable thumbnail strip, ESC to close.
- **Editor**: field editing including the Markdown description; folder rename from the predefined-candidates list (§4.1).
- **Follow** (a distinct mode from viewer/editor): sequential playback of the tutorial's files, recording watch progress and duration; note-taking (create/view/edit); bookmarking. Progress sync follows §7/§9.6.
- **Web**: search/browse tutorials the user has access to; follow a tutorial from the browser, with the same progress/notes/bookmarks behavior as the desktop "follow" mode.

### 13.3 Reference images plugin

Viewer/editor similar in shape to the tutorial plugin (no "follow" mode), with type-specific features:

- **Tagging at two granularities**: archive-level and per-image. Per-image tags are stored as app-managed mutable metadata alongside `.rehu`/screenshots (not inside the immutable, checksummed zip), keyed to images by index/filename — see §4.6 for the screenshot-vs-zip-content distinction and the stale-overlay warning when a zip is manually refreshed.
- **Non-destructive redaction**: rectangle/ellipse regions with an effect type (mosaic/blur/solid color), stored as app-managed metadata (§4.6) and applied at render time — the original image inside the zip stays byte-identical and covered by the checksum manifest (§4.5). A toggle controls whether redaction is shown; likely a per-user (not just per-device) preference.
- **Search**: tag-based filtering (select from existing tags, e.g. `female`, `back`, `3/4`) is straightforward. Free-text natural-language search (e.g. "3/4 view of male face") is harder and should be scoped as: a cheap fallback (fuzzy match against existing tags/synonyms) now, with a semantic/embedding-based approach as a possible later upgrade — not assumed solved by simple string matching.
- **Sketch-practice slideshow**: timed rotation (e.g. 20 sec/1 min/5 min per image) through a filtered image set, for drawing practice. Records a **session log** (ordered list of images shown, with timestamps/durations) distinct from any lifetime per-image view stats; the user can favorite/tag images from that session afterward, using the same per-image tagging mechanism as elsewhere — not a separate tagging system.
  - **Drawing comparison/critique** (exploratory, not committed): proposed as a two-stage pipeline — (1) deterministic facial/pose **landmark detection** run on both the reference image and the user's drawing, producing measurable deltas (eye height, symmetry, proportions), followed by (2) a cheap LLM call that narrates those numeric deltas in plain language. This is preferred over asking a vision-capable LLM to critique the images directly, which would be less reliably grounded in anything actually measured and more expensive per call. Caveat: landmark detectors are mature for photos but may not generalize well to loose hand-drawn sketches — this needs early prototyping against real sketches before being relied on. Treated as a v2/exploratory enrichment, not a dependency of the core sketch-practice feature.

### 13.4 Daz3D plugin

Viewer/editor similar in shape to the others, plus a **custom action**: install/uninstall the plugin/asset into the user's local Daz3D installation. Tracked per user *and* per box (i.e. "installed on which machine, by whom, when"), since this is a system-integration side effect rather than a view/edit operation — it's the first concrete example motivating "custom actions with tracked side effects" as a first-class plugin capability (§13.1), not just schema/viewer/editor/web.

### 13.5 Shared capability worth extracting

"Follow tutorial" (§13.2) and the sketch-practice slideshow (§13.3) both want a **timed/sequential presentation** capability, just configured differently (tracked progress + notes/bookmarks vs. a fixed-duration rotating display + a session log). Worth designing this as one shared core capability that plugins configure, rather than reimplementing similar sequencing/timer logic independently in two plugins.

## 14. Functional Requirements Carried Into the Architecture

Consolidated list of requirements established across discussion, checked against the design above:

- Browse content across any node from any other node; resources with no live access route show cached info marked offline rather than disappearing (§10.3).
- Request a local copy of a resource for offline use; local copies are marked as copies and tracked as instances (§10.2).
- Duplicate detection across the catalog, with a review UI for ambiguous cases (§10.4, §10.5).
- Per-resource notes, view/watch progress, and bookmarking; ability to delete local viewed files on request.
- Track *why* something was deleted/skipped (via tags/notes), to avoid re-buying or re-downloading it later.
- Admin-managed users and access control: full access, per-resource grants, or dynamic tag-based grants — swarm-propagated, enforced server-side at the serving node (§6.7, §6.9).
- No remote/off-LAN access by design; reach the swarm from outside via a VPN into the home network (§17.2).
- Checkout → offline use → sync-back of notes/progress, including the implicit-checkout case when storage itself becomes unreachable (§12), and the deliberate borrow/library-shelf case (§11). In v1, offline editing covers per-user state only; resource metadata is online-only-editable (§7).
- Borrows recorded in the user's meta block, supporting multiple simultaneous devices and an explicit return step (§11.4).
- Seamless node handoff during active playback (§9.6).
- Web UI usable from an iPad as a thin client served by a node — a household always-on box at home, or the laptop's node while away (§11.5).
- The Qt app connects to any node on the LAN and always operates as a node client, even on the same machine; editing a node's `.rehuco` browses that node's files (§5.1).
- Self-mapping of shared storage across nodes via fingerprint files, including detection of double-primary misconfiguration (§9.9, §9.10).
- Node benchmarking/grading to drive task-dispatch decisions quantitatively (§9.11).
- Self-determined fastest/safest move/rename, with checksum-gated cross-filesystem moves (§9.12).
- Extensible resource types via plugins, with tutorial, reference-images, and Daz3D as the initial set (§13).
- Scheduled archival of a borrowed resource's video files on return (fully or selectively, keeping chosen files), preserving metadata/images/extras and tagged as archived (§11.3).
- Durable, configurable local retention of offline-media and remote-node metadata for offline browsing and rebuild survival (§9.8).

## 15. Acquisition and Migration Tooling

These features don't belong to the core data/swarm architecture, but they're what makes the catalog *populatable and maintainable* at scale (thousands of tutorials), so they matter for day-to-day usability. All are productivity aids feeding the editor the user reviews — assistive, not unattended.

### 15.1 Three drag-and-drop input aids (restored from TutCatalog4)

- **HTML selection → Markdown into the description editor.** Selecting content on a web page and dropping it on the description editor: the drop's `text/html` payload is converted to Markdown by a deterministic library (html2text-style) and inserted at the cursor. No LLM, no per-site logic, no fetching — it just transforms whatever HTML the browser handed over (with a sanitize/clean pass first, since pasted web HTML is messy). The cheapest and lowest-maintenance of the three; restore it early.
- **Image drag → download, rescale, auto-name screenshot.** Dragging an image from a browser onto a designated widget: download it, rescale to ≤300px wide (Pillow), and save as the next unused `imageXX` screenshot name. No LLM. Pairs with the screenshot-name normalization in migration (§15.3).
- **URL drop → extract tutorial info.** Dropping a URL: fetch/render the page and extract `{title, author, publisher, duration, description, …}` into the resource's fields. See §15.2 — this is the one with real nuance.

### 15.2 URL extraction via a local small LLM

The TutCatalog4 approach (geckodriver + BeautifulSoup + hand-maintained per-site scrapers) broke constantly because each site needed bespoke parsing logic kept up to date by hand. The modern approach removes that maintenance burden: fetch the page text and hand it to a model for **structured extraction into a fixed JSON schema**, eliminating per-site parsing code.

- **Local model is the right call** — zero per-call cost (run thousands of times across the catalog), no external dependency, offline, private. This is high-volume personal productivity, where a small local model beats a cloud API on every axis except peak quality, and extraction doesn't need peak quality.
- **Hardware fit:** a 7–8B model at 4-bit quantization (e.g. Qwen2.5-7B-Instruct) runs comfortably on the RTX 4070 (12 GB, fast) and on the Mac mini M1 (16 GB unified, slower but usable). Worth testing whether a 3–4B (Qwen2.5-3B) suffices for even more speed; reserve 14B (4070 only) for if 7B visibly struggles. Dispatch this to a capable node (4070 box or Mac mini), explicitly **not** the QNAP (§9.7/§9.11).
- **Reliability comes from constraining output, not from model size.** Use **grammar/JSON-schema-constrained decoding** (llama.cpp GBNF, Ollama format, Outlines, LM Format Enforcer) so the model *cannot* emit invalid structure or extra fields — this removes the entire "formatting" failure class and leaves only "did it find the right value," which small models do well. Pair with an explicit **"return null when a field isn't present"** instruction so the model leaves blanks rather than hallucinating a plausible-but-wrong value. With both, a constrained 7B is "right on common cases, never confidently wrong" — exactly the bar for an assistive tool the user reviews before saving.
- **The harder half is fetching/rendering, not extraction.** JS-heavy course pages (Udemy, Gumroad) may still need a headless browser to render before extraction, and a readability/main-content trim before the model keeps quality up on long pages. So per-site effort drops a lot but doesn't vanish — it moves from "parse this site's DOM" (brittle) to "render and trim this site's page" (more robust).
- Implemented as a **task-queue job** (§3), like other heavy work.

### 15.3 Migration: `.tc` → `.rehu` as format-version 0

Opening an old `.tc` file offers migration actions: convert `.tc` (YAML) → `.rehu` (JSON), and normalize the non-uniform screenshot names into the uniform `imageXX` scheme. This is the **first concrete instance of the format-versioning mechanism (§4.10)** rather than a one-off script: `.tc` is simply "format version 0," and migration is the upgrade-on-read/import rule applied to the oldest format. Checksum generate/verify (§4.5) belongs alongside the migration actions in the same tooling.

### 15.4 Deferral

Per the user's stated priorities, the acquisition aids (especially §15.2's LLM extraction) are **deferred until after the tutorial web viewer is working** — manual entry suffices in the interim. The HTML→Markdown and image-drag aids (§15.1) are cheap enough to restore earlier if convenient, but none of §15 blocks the core local-viewer / tablet-watching milestones.

## 16. Code Organization, Packaging, and Deployment

A monorepo with **uv workspaces** is the chosen structure, driven by three concrete pains: refactoring code between the shared library and the apps (currently a multi-repo/submodule dance of coupled commits), tooling confusion over *which* `.venv` is active (a multi-root VSCode layout has one venv per root, and tools — including AI coding assistants — guess wrong), and independent PyPI publishing of the shared libraries.

### 16.1 Why uv workspaces

- **One shared `.venv` at the workspace root**, containing every member as an editable install. This eliminates the "which venv?" ambiguity at its source: there is exactly one environment, every package is always importable from it, nothing to guess. (This is the strongest single reason for the move.)
- **Atomic cross-package refactors.** Moving a widget from an app into the shared library becomes one commit in one repo, instead of a commit in the submodule plus a pointer-bump commit in the consumer.
- **Single lockfile, consistent versions** across members — which for a set of sibling PySide6 apps sharing a library is a benefit (it forces version compatibility), not a limitation.

The one real constraint workspaces impose: all members resolve against **one dependency set**, so two members needing conflicting versions of the same package would fail to resolve. For this project (all the author's own apps over a shared Qt-era stack) that's acceptable and even desirable.

### 16.2 Three packages, mapping onto the node/agent/shared-library split

The packaging boundary mirrors the architecture's node/agent split (§5.1):

```
rehuco/                   # monorepo root
  pyproject.toml          # virtual workspace root: [tool.uv.workspace] only, no [project]
  uv.lock                 # single lockfile
  .venv/                  # the one shared environment (development only)
  packages/
    rehuco-core/          # shared library: field toolkit, .rehu model, plugin base — PUBLISHABLE
    pyside_ibo/           # generic PySide widgets/utilities — PUBLISHABLE
    pyside6-scintilla/    # PUBLISHABLE
    pyside6-lexilla/      # PUBLISHABLE
  apps/
    rehuco-node/          # headless service: depends on rehuco-core + FastAPI/uvicorn/zeroconf
    rehuco-agent/         # desktop GUI: depends on rehuco-core + PySide6/scintilla/ads
```

The **virtual workspace root** (no `[project]` table, only `[tool.uv.workspace]`) is a pure organizational container — it can't itself be published and holds no app code, keeping the root clean. Shared libraries are publishable leaf packages (they depend only on PyPI packages, never on the apps, so they carry no workspace-internal dependencies that would block publishing).

### 16.3 PyPI publishing and `uv tool install`

- Each member has its own `pyproject.toml` (name, version, build backend) and **publishes to PyPI independently** — `uv build --package rehuco-core && uv publish`. The monorepo structure is invisible to PyPI; it just sees a normal wheel.
- The node and agent are installable as tools: **`uv tool install rehuco-node`** (ideal — headless service, console entry point) and **`uv tool install rehuco-agent`** (works for the GUI; native installers / file-association registration are a later polish for wider distribution (§16.8), not needed for the author's own machines).
- **Three packages, not one-package-with-extras.** Extras were considered (`rehuco[node]` / `rehuco[app]`) but rejected for the key reason below: extras are *additive and cannot subtract a base dependency*, so any GUI dependency reachable from the base would still be pulled by `rehuco[node]` — fatal on the TS-230. Separate packages make "the node has no GUI dependencies" **structural rather than carefully-maintained**, and let each package carry its own `requires-python` floor.

### 16.4 The TS-230 / old-glibc constraint: deploy artifacts, don't sync the workspace

The QNAP TS-230 (glibc 2.23) cannot host the agent's PySide6 stack (no compatible wheels). The workspace's single shared `.venv` means `uv sync` at the root tries to install **everything**, including PySide6 — so the workspace itself must never be synced on the TS-230. The resolution rests on a clean separation:

- **The monorepo workspace is the *development* environment; it is not what gets deployed.** Development happens in the full workspace on capable machines (where PySide6 installs fine).
- **Deployment installs individual published packages.** The TS-230 runs `uv tool install rehuco-node` (or installs the built `rehuco-node` wheel into a plain venv) — which pulls `rehuco-node` + `rehuco-core` + server deps and **never references the agent package at all**, because `rehuco-node` doesn't depend on it. The agent isn't "excluded"; it's simply not in the node's dependency tree. The QNAP never sees the workspace.
- **Platform markers on the agent's GUI dependencies** keep even a full workspace lock resolvable in the presence of a platform that can't host them, and prevent accidental installation where they can't go:
  ```toml
  # rehuco-agent/pyproject.toml
  dependencies = [
    "rehuco-core",
    "PySide6; platform_machine != '<ts230-arch>'",   # marker false on the QNAP
    # …other Qt deps similarly gated
  ]
  ```
  (Exact marker keys on whatever uniquely identifies the TS-230 — `platform_machine` for its CPU arch, or `python_version` if it's pinned to an old interpreter.)

- **`rehuco-node` carries its own lower `requires-python`** so it can target the TS-230's older Python independently of the agent's newer floor — something a single-package-with-extras layout could not do (the workspace resolves to the *intersection* of all members' `requires-python`, so the agent's needs would otherwise constrain the node).

### 16.5 TS-230 as a deployment-target canary (continuous compatibility check)

Verifying the node runs on glibc 2.23 is testing the **artifact**, not the workspace:

- **Dev/iteration and the main test suite** run on capable machines: `uv run --package rehuco-node pytest`.
- **A separate, early, recurring step builds `rehuco-node` and installs + smoke-tests it on the actual TS-230** (or a glibc-2.23 container that mimics it), exactly as it will really be installed. This is the dependency canary flagged as a risk in §17.2: if any node dependency (FastAPI, uvicorn, zeroconf, cryptography, pydantic-core, …) lacks a glibc-2.23-compatible wheel, this surfaces it — and it's a *node*-dependency problem to solve (e.g. an older pydantic), entirely independent of the agent's PySide6, which never enters the node's picture. Running this continuously keeps the QNAP-compatibility promise verified rather than discovered late.

### 16.6 Migrating existing repos

**Decided: start the monorepo fresh.** Per-repo git history of the old apps isn't valued enough to preserve (the author is comfortable starting clean — "what's another repo"). The old repos (`resource-hub`, `tutcatalog5`, `tutcatalog4`, `pyside_ibo` as a standalone) are kept read-only as an archive/reference, not grafted in. This avoids the `git subtree`/`git-filter-repo` fiddliness entirely. (`pyside_ibo` moves from submodule to a first-class workspace member, §16.2.)

### 16.7 Dependency licensing policy

**Principle: the choice of the final application's license must stay with the author, not be forced by a dependency.** GPL is fine *by deliberate choice* for a final app; being *compelled* into GPL by a linked library is not acceptable — it removes the author's freedom and entangles the reusable libraries (`rehuco-core`, `pyside_ibo`, etc.) that are meant to be independently publishable under whatever license the author picks. (This principle is already evidenced by the author writing an MIT-licensed `pyside6-scintilla` rather than depending on a copyleft alternative.)

Concrete consequence for **docking**:

- **Use `pyqtads` (Qt-Advanced-Docking-System), not KDDockWidgets.** Both are mature and feature-comparable (detach/float/nest/auto-hide/delete-on-close), and KDDockWidgets is in some respects the more capable *framework* (KDAB pedigree, native QML docks, deeper customization). But:
  - **KDDockWidgets is GPL 2.0/3.0** (or paid commercial). Linking it makes the *entire agent* a GPL combined work — cascading into the publish plan (§16.3) and risking entanglement of the reusable libraries. This is a property of the license, not something the binding/packaging can engineer around.
  - **`pyqtads` is permissively licensed (LGPL)** — it can be linked from an app of any license without forcing the app's license — **and ships prebuilt PySide6/PyQt6/PyQt5 bindings on PyPI**, so it drops into the uv workspace as a normal dependency with no build step.
- The packaging objection to KDDockWidgets (no PyPI wheel; bindings must be built from source via shiboken+CMake+libclang) is one the author *could* solve — the same CI-built-binding work already done for `pyside6-scintilla` (shiboken) and `pyside6-lexilla` (nanobind). So bindings are **not** the blocker. **The license is the blocker**, and it is not solvable by effort.
- KDDockWidgets is therefore foreclosed for this project. If the QML-in-`pyqtads` approach (QQuickWidget hosted in a widget dock) proves inadequate, the response is to constrain how QML is used (e.g. keep QML surfaces in non-detachable docks, or reduce the QML footprint) — **not** to switch to KDDockWidgets.

### 16.8 Desktop distribution, file association, and app identity

Distribution splits by audience, structurally (as the package split does, §16.2):

- **`rehuco-core` and `rehuco-node` are pure PyPI** (§16.3) — a library and a headless service; no GUI identity, no file association.
- **`rehuco-agent` is dual-channel.** `uv tool install` suffices for the author's own machines and developers (§16.3); wider end-user distribution additionally needs a **native app identity** — icon, file association, taskbar pin/running indicator, an installer — that a bare install cannot provide.

Two design facts shape the choice:

- **File association is OS-specific, and macOS is the binding constraint.** Only a real application bundle can be a document type's default handler there, and the opened path is delivered as an in-process event rather than a command-line argument — so it must reach the already-running single instance (§5.4). Windows and Linux register the association declaratively and need no elevation.
- **Windows app identity (icon / pin / running) is an identity-registration concern, not a "must be a compiled binary" one.** A prior version (`resource-hub`) achieved a correct taskbar icon/pin/running indicator only from a frozen PyInstaller build, but the real requirement is a stable per-application identity plus an ordinary per-app launcher — both available without freezing (the standard entry-point launcher already serves). Freezing the app into a single binary is therefore **not** required.

**Decision: package end-user builds with Briefcase, not PyInstaller.** Briefcase does not freeze — it pairs a thin launcher with an embedded interpreter and the app's source, and declares icon, identity, file association, and installer from `pyproject.toml`, so the OS-specific registration is generated rather than hand-maintained. The deciding reasons are **reduced fragility and declarative app identity**, not build speed. MSIX is a possible later upgrade for the strongest Windows identity. This is wider-distribution polish — not needed for A0 or the author's own machines — and the file-association and single-instance mechanics it rests on are de-risked by a dedicated spike (plan: Pre-work) before A0 relies on "double-click opens."

### 16.9 Auto-update

The agent should detect a newer release, flag it, and offer to install. Design positions:

- **Version checking is cheap and uses a public source.** The repo is public, so either GitHub Releases or the PyPI metadata serves as the version oracle, via a small periodic poll.
- **Applying an update is the hard, OS-specific part**, with real prerequisites: a running application cannot overwrite itself in place, system-level installs need elevation, and signed/notarized artifacts are required or the OS blocks the download. The chosen approach is to **delegate the privileged install to the platform's installer** rather than hand-write a self-replacing updater.
- For the `uv tool` / pip channel, "update" is simply re-installing the newer package.

Code-signing / notarization is an unpriced prerequisite (§17.2). Auto-update is end-user polish on the same track as §16.8, deferred past the personal critical path (plan: deferred).

## 17. Explicitly Out of Scope / Not Yet Designed

Flagging gaps so they're a deliberate choice rather than an oversight.

### 17.1 Resolved or scoped since the first consolidation

- **Metadata-conflict during offline editing** — previously an unacknowledged contradiction between §7 ("single writer, no conflict") and §12 ("cache stays editable offline"). Resolved for v1 by making resource metadata online-only-editable (§7); only per-user state is offline-editable. The hard multi-writer-metadata merge is a future hook, not v1 work.
- **Instance-registry / offline-instance persistence** — the rebuild-from-scratch model was imprecise. Now bounded (§2): retained metadata copies (§9.8) survive rebuild by rescan; transient instances re-register on reconnect; borrows persist via the user meta block (§11.4).
- **Per-image metadata location** — clarified (§4.6): app-managed mutable metadata alongside `.rehu`, never inside the immutable checksummed zip.
- **Scanning strategy** — incremental, version-aware reconciliation is now the normal mode; full rescan demoted to recovery (§4.7).
- **Node identity scheme** — replaced the pairing-secret design with Syncthing-style cert-hash device IDs (§6.4), where identity *is* the key and the introducer model (§6.5) matches the existing hub-and-spoke choice.
- **App/filesystem coupling** — resolved by making the Qt app always a node client (§5.1), removing the local-vs-remote dual code path.
- **Cross-node storage topology** — was reactive per-resource UUID matching only; now also proactive via fingerprint self-mapping (§9.9), which additionally guards the single-primary rule (§9.10).
- **Deletion / tombstone propagation** — resolved (§7): deletion is an ordinary logged action whose tombstone is its position in the version vector, so offline nodes apply it on reconnect and rescans don't resurrect. Delete-vs-concurrent-edit surfaces in the verdict queue (§10.5) rather than silently applying. Borrow-vs-delete/archive has an explicit resolution (§11.6).
- **Clock skew / ordering** — resolved (§7): ordering is by per-node-counter version vector, clock-independent; wall-clock timestamps are no longer load-bearing. History is a separate, prunable activity log.
- **Per-user authentication** — resolved (§6.7): salted Argon2id hashes propagated to every node (since any node can serve a login), passwords never stored/transmitted; thin tablet logs in via session against its serving node.
- **Visitors / cross-swarm sharing** — resolved (§6.8): visitors never join as nodes (guest account or stripped export/import instead); no cross-swarm federation.
- **Access control model** — resolved (§6.9): rules are swarm-wide propagated config (not per-machine `.rehuco`), enforced server-side at the serving node, with tag-grants evaluated dynamically. Remaining work is the concrete rule grammar/schema, not the model.
- **Local file layout** — resolved (§4.8): `.rehuco` (per-machine config), `.rehudb` (disposable cache), `.rehusw` (durable, propagated swarm info).
- **Startup consistency for access rules** — resolved (§6.10): serve-after-resync, stated as "catch up to the most-current reachable source, else serve last-known," with a `.rehusw` version marker making "more current" decidable. Resync source resolved by §6.6.
- **Registry home** — resolved (§6.6): preferred authority (always-on box) when reachable, else chatter for highest version, else last-known; single node is the degenerate case. Single-writer admin config + version markers means no consensus protocol needed.
- **Single-node / bootstrap operation** — resolved (§8.1): the lone node is the base case — its own registry authority, serves immediately without waiting for peers; create-swarm and single-node-forever are the same path.
- **Node vs. agent split** — resolved (§5.1): node = headless service (runs everywhere incl. QNAP); agent = desktop GUI (tray + viewer/editor + catalog), a node client, GUI machines only. Independent lifecycles; quitting the agent leaves the node serving. "Admin" is a logged-in user's privilege, not a separate build.
- **App readiness / responsiveness** — resolved (§5.2): per-operation readiness, not one global gate; local-file and cached operations never block on swarm sync; all swarm chatter is async background (task queue) surfaced as status.
- **Local-file vs. swarm mode / no-node viewing** — resolved (§5.3): the single-file viewer needs no node or login (viewing a local file isn't access-controlled); swarm mode enriches when a node/session is present.
- **Single-instance & file association** — resolved (§5.4): bind-or-forward single-instance, one main agent hosts both scopes, forwarded opens never block on login, stale-socket reclaim, socket scoped per-user-and-swarm.
- **Login persistence** — resolved (§6.7): agent caches a session token (not the password) in the OS secure store; revocation reaches the agent when the token fails.
- **`.rehu` write integrity** — resolved (§4.9): universal atomic temp-then-rename; managed files route exclusively through the owning node (single writer); unmanaged files written directly by the agent; import is the explicit unmanaged→managed hand-off.
- **`.rehu` schema format versioning** — resolved (§4.10): per-file format-version field; newer reader upgrades older files, older reader preserves unknown fields rather than dropping them; import is an upgrade point.
- **Plugin block model** — resolved (§13.1a/§13.1b): plugin fields in separate keyed, independently-versioned blocks; exactly one live block per `type` (installed-ness doesn't promote inert blocks); save-persistence invariant (live type, or never-claimed foreign payload) with claim-then-abandon dropping on save; generic fallback editor with carry/map/drop and provenance-aware flagging; discards logged.
- **Plugin spectrum (declarative ↔ code)** — resolved (§13.1): simple types are declarative field-lists over a shared field toolkit (no code, no trust surface); rich types are code plugins using the same toolkit plus custom widgets/actions. Unifies the code-plugin and TutCatalog5 `.rehuco`-declared-fields ideas.
- **Resource browsers** — resolved (§13.1c): generic browser (common columns) + per-type browsers (plugin-contributed columns + cover rendering), table/shelf modes, click-to-filter on tag/author/publisher restored from TutCatalog4.
- **Acquisition & migration tooling** — specced (§15): three drag-drop aids (HTML→Markdown, image→screenshot, URL→extract), local-LLM extraction with constrained decoding, `.tc`→`.rehu` migration as format-v0. Deferred until after the tutorial web viewer.
- **Code organization, packaging & deployment** — resolved (§16): monorepo with uv workspaces (single `.venv` fixes the venv-confusion and makes cross-package refactors atomic); three published packages (`rehuco-core`, `rehuco-node`, `rehuco-agent`) mapping onto the shared-lib/node/agent split; `uv tool install` for node and agent; TS-230 installs the node *artifact* (never the workspace), with platform markers on agent GUI deps and a continuous TS-230 install-canary making the glibc constraint structural rather than careful.
- **Offline revocation limitation** — acknowledged as a deliberate accepted boundary (§6.10): revocation can't reach an already-held local copy that never reconnects; trusting household members who kept a copy is an explicit non-goal. Revocation does apply on reconnect.
- **Desktop distribution, file association & app identity** — analyzed (§16.8/§16.9): the agent is dual-channel (`uv tool` for the author's own machines/devs; a native installer for wider reach); file association is OS-specific with macOS as the binding constraint; Windows taskbar identity is an identity-registration matter, not a reason to freeze the app; **Briefcase** is chosen for end-user installers over PyInstaller, with MSIX a possible later upgrade; auto-update checks a public version oracle and delegates installation to the platform installer. All wider-distribution polish, off the personal critical path; the OS mechanics are still to be proven (§17.2).

### 17.2 Still open

- **Full `.rehu` schema** — field ownership (common vs. plugin) is settled (§4.1, §13.1); the complete field list/types per plugin is being designed separately. Archival is a tag (§11.3), not a schema state. The schema must now also carry the version vector and activity log (§7) and the user/auth records (§6.7).
- **Access-rule grammar/schema** — the *model* is settled (§6.9: swarm-propagated, server-enforced, full/per-resource/dynamic-tag grants). What's not yet specified is the concrete representation: how a grant is written, how per-resource and tag-grants combine (additive? can a deny override an allow?), and where exactly it sits in the propagated registry.
- **Remote (off-LAN) access** — *deliberately out of scope, not a gap.* The whole trust/discovery model (§6) is LAN-local by design. The app provides no remote-access mechanism and will not put a personal media catalog on the public internet. A user who needs access from outside, without standing up their own mobile node, should **VPN into the home network** (WireGuard/Tailscale/etc.) — at which point they are "on the LAN" and everything works unchanged. This cleanly delegates remote-access security to mature purpose-built software instead of reinventing it in the app; the app stays simple and LAN-trusting, the VPN decides who may reach the network at all.
- **Instance-registry replication detail** — the *home* is resolved (§6.6: it lives with the preferred authority / propagates like the rest of the registry). What's not yet detailed is the concrete shape of the instance registry's own propagation and how transient instances (active checkouts) register/expire within it — the location question is settled, the replication mechanics aren't fully drawn.
- **Activity-log pruning policy** — the mechanism is decided (prune by age X / count Y, never dropping the current state-defining event, §7); the actual default thresholds and whether they're per-resource or global aren't set.
- **Export/import mechanics** — the rules are decided (keep UUID, scrub vector/log/per-user-state/instance entries, §6.8); the concrete on-disk export format and the import-side UUID-collision handling aren't designed.
- **Block-level transfer for re-copies** — noted (Syncthing's chunk-hash-and-transfer-only-diffs approach) as worth borrowing *narrowly* for refreshing a backup/move where a prior version exists at the destination; no help for first-time copies. Not designed; lower priority.
- **Admin identity permanence** — flagged in §6.6a, not resolved (distinct from registry home, which is decided).
- **Online-only and mixed local/online resources** — needs schema representation; not detailed.
- **Udemy integration** — registered courses are hard to track; no scraping/API/import approach discussed.
- **3D objects as a resource category** — mentioned alongside Daz3D but not mapped to a plugin design.
- **Shared timed-presentation capability** — identified as worth extracting (§13.5) but not designed.
- **Drawing comparison/critique pipeline** — exploratory (§13.3); needs prototyping before being committed.
- **Borrow automation** — manual vs. automated power-down of the source box is unresolved (§11.2).
- **File-association + app-identity verification** — the *direction* is decided (§16.8), but the OS mechanics aren't yet proven on current versions: a macOS application bundle actually delivering the opened file into the bind-or-forward single instance (§5.4), and a Windows default-handler + per-app identity actually producing double-click-open plus taskbar pin/running. Slated as a Pre-work spike (plan). **Code-signing / notarization** (Apple Developer ID, Windows certificate) is an unpriced prerequisite for shipping updates (§16.9), not yet committed.
- **First build slice** — not yet chosen.
- **Concrete technology stack** — PySide6 (+ `pyside6-scintilla`, `pyqtads` for docking — chosen over KDDockWidgets on licensing grounds, §16.7 — selective QQuickWidget use for QML surfaces), SQLite + SQLAlchemy for the cache, FastAPI + HTMX + Pico CSS for the web UI, zeroconf for discovery, `uv` for environment management — strong candidates. The QNAP's old glibc (2.23) remains a per-dependency risk, but it is now *structurally contained*: the node is a separate package with no GUI deps, deployed as an artifact (not the workspace), with a continuous TS-230 install-canary (§16.4, §16.5). Specific node-dependency wheel compatibility (pydantic-core, cryptography, etc.) on glibc 2.23 still needs the actual canary run to confirm. Stack not yet finalized.
