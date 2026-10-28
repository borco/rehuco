# §9. Mounts, `.rehuco`, and Cross-Box Visibility

[[[mounts-and-storage]]]

## §9.1 The problem

[[[mounts-and-storage#the-problem]]]

One share, many machines, many paths. The same folder on the NAS is `U:\Tutorials` on the Windows PC,
`/System/Volumes/Data/mount/DATA/Tutorials` on the Mac mini and `/mnt/nas/Tutorials` on a Linux box; a folder on one
PC's own disk is reachable from the others only once that PC shares it, under yet another path. The catalog must know
that these are one place, keep each machine's cache current when another machine changes a file there, and open the
same `.rehuco` on every one of them.

## §9.2 Identity is the UUID, not the path

[[[mounts-and-storage#uuid-not-paths]]]

A resource reached by two paths — two machines' mounts of one share, a backup on a shelf, a borrowed copy — is
recognized as one resource because its `.rehu` **UUID** matches, never by guessing that one path corresponds to
another ([[instances-and-dedup#uuid-is-lineage]]). A key is a location, not an identity ([[nodes#access-seam]]).

**A rename is a filesystem operation on the machine that issues it.** Within one process a job holds a
`ResourceLocation` rather than a path, and the rename rewrites it ([#241](https://github.com/borco/rehuco/issues/241));
the other views follow through the notifier's `Moved` event. Another machine learns of the rename the same way every
change travels: the SMB server reports it, that machine's notifier announces it, its cache follows
([[mounts-and-storage#out-of-band]]). A request that still names the old path arrives at a file that is no longer there
and is refused with the reason, not guessed at. There is no cross-machine rename request and so nothing to coalesce.

## §9.3 `.rehuco`: the user's roots, mapped per machine

[[[mounts-and-storage#rehuco-scope]]]

- [#514: feat: a shareable .rehuco — a location per root, per-machine mappings, detected storage](https://github.com/borco/rehuco/issues/514)

A **`.rehuco`** file names the folder roots to catalog, and is **shareable across machines**: it may sit on the share
and be opened from every box, or be copied around. **By default it is a local file** — *New* proposes the app folder
and *Open* starts there; putting one on the share is the user's choice, and nothing else changes. It declares:

- the **roots**, each with a stable **id** the cache keys its rows on, a **label** (defaulting to the folder's name,
  made unique with a suffix on a clash; what the browser shows and what a folder filter addresses,
  `folder="<label>/<relative path>"`, [[plugins#browsers]]) and a machine-independent **location** (below) — nothing
  that is a fact about one machine; where each machine finds a root is that machine's **mapping**, kept apart. **As
  built (format 3) these sit inline; with [[mounts-and-storage#rehuroot]] (format 4) each root is a `.rehuroot` file
  of its own and the `.rehuco` holds only an ordered list of references to them;**
- which plugins ([[plugins#overview]]) to load;
- a **home** for each kind of grouping-entity document — creators, collections, learning paths
  ([[plugins#grouping-entities]]) — as `homes: {"creator": {"root": <root id>, "path": <relative path>}, "collection":
  …, "learning_path": …}`, each a folder under one of its roots, the three free to be one folder. A new or materialized
  entity of that kind is created there, and the location editor offers it as a move. It is set from a root's or a
  folder's context menu in the Root Catalog panel, *Set as Home for Creators / Collections / Learning Paths*, and that
  row carries the role's glyph; a home whose root is removed, or whose folder is gone, is unset and the panel says so.
  With no home set, creating an entity asks for one first. *Discovery* of existing entity documents needs no home — it
  is type-based, so the scanner finds them wherever they sit in any scanned root.

**A root's identity is its location; what differs per machine is its mapping.** The location is the same on every box:
for a share, the server and share path (`//nas/data/Tutorials`), read from this machine's mount table when the root is
added (`WNetGetConnection` on Windows, the mount table on macOS and Linux); for a folder on one machine's own disk, that
machine's name and path (`//ryzen-5600/d/Downloads/FOO`). The host is lower-cased, and a server spelled by name on one
machine and by address on another is two locations.

```json
{
  "format_version": 3,
  "id": "…",
  "roots": [ { "id": "…", "label": "Tutorials", "location": "//nas/data/Tutorials" } ]
}
```

**A mapping is kept per machine, in that machine's data folder, never in the `.rehuco`.** It says where this machine
finds a root and carries what is a fact about this machine rather than about the root — the folder and the storage —
plus whether the user chose to skip the root:

```json
{
  "format_version": 1,
  "rehucos": { "<rehuco id>": {
    "<root id>": { "path": "U:\\Tutorials", "storage": "network" },
    "<root id>": { "skipped": true }
  } }
}
```

One machine writes it, so it takes no lock. The agent and the node of one machine read the same file
([[nodes#node-actions]]), so a root mapped in the agent is served by the node. A mapping is keyed by the rehuco id and
the root id, so moving or renaming the `.rehuco` keeps it; a machine that is renamed loses nothing, since nothing in the
shared file names it. With `.rehuroot` the rehuco level goes: a root's id is the same in every catalog that lists it,
so a mapping is keyed by the root id alone ([[mounts-and-storage#rehuroot]]).

- **The storage kind is detected, not declared** — local disk, network share, removable drive or disc — from the drive
  type on Windows and the mount table elsewhere, when the mapping is written; the notifier picks its backend from it
  ([[mounts-and-storage#out-of-band]]) and retention takes its default from it
  ([[mounts-and-storage#durable-retention]]). There is no user override: the system marks them.
- **Opening the file on a machine with no mapping resolves what it can and asks for the rest.** A root whose server and
  share this machine mounts, or whose location names this machine, is mapped from the mount table or the drive table
  without asking; the rest are listed in a wizard with Browse and Skip per row. A skipped root stays **visible but
  disabled** — not scanned, not browsed, not served by the node — and is not asked about again; a root neither mapped
  nor skipped (the wizard was cancelled) is asked again at the next open. *Map…* in the Roots view maps a root later,
  once the share is mounted or the folder shared, and replaces a skip. A root a machine cannot reach by nature (another
  box's local disk, not shared) sits there the same way.
- **The `.rehuco` changes only when the roots do** — one added, removed, relabelled or moved — so two machines rarely
  save it at once, and mapping a root never writes it. The save goes through the same lock as a `.rehu`
  ([[sync#overview]]) and then compares the file with what this machine last read or wrote: if another machine changed
  it since, nothing is written, the catalog is read again and the user is told to repeat the edit. There is no merge of
  structural edits.
- **Format 2** (plain paths and a user-declared storage) is not migrated: a root's location is computed on the machine
  that finds the folder, so the file is made again by adding its roots to a new catalog. Opening one says so.

**Per `.rehuco`, not per machine singleton.** A machine may keep several `.rehuco` files — each a set of roots browsed
together — and the agent opens one at a time ([[data-model#local-file-trio]], #371). Removing a root asks first, states
that its files stay where they are, and drops only the root's cached entries ([[data-model#cache-schema]]).

**Roots do not overlap** within one file ([[multiplicity#instances]]), and no root has an owner.

### §9.3.1 `.rehuroot`: a root as a file of its own

[[[mounts-and-storage#rehuroot]]]

- [#577: feat(core): the .rehuroot file — id, label, location, layouts, fallbacks; .rehuco format 4 as an ordered list of references; mappings keyed by root id; path templates with /](https://github.com/borco/rehuco/issues/577)
- [#578: feat(agent): Add Roots — pick existing .rehuroot files or a folder with a default layout; default layouts in settings; layouts and fallbacks on the root's properties](https://github.com/borco/rehuco/issues/578)
- [#579: feat(agent): the path row's root destinations — rename in place within the root, the verified move across roots once #339 lands, greyed with the reason otherwise](https://github.com/borco/rehuco/issues/579)

With a root's id, label and location inline in the `.rehuco`, the same folder listed by two catalogs is two roots:
two ids, two mappings, two caches, and nothing that is a fact about the root — how it is laid out — has a home at
all. So **a root becomes a file of its own**, `<name>.rehuroot`, and **the `.rehuco` becomes an ordered list of
references** to such files and nothing more about a root: its role is to aggregate and order roots.

```json
{
  "format_version": 1,
  "id": "…",
  "label": "Tutorials",
  "location": "//nas/data/Tutorials",
  "layouts": { "*": "*" },
  "fallbacks": { "authors": "Unknown" }
}
```

- **It never lives inside the root.** [[mounts-and-storage#fingerprint-map]] retired files dropped into the user's
  folders, and that holds. A `.rehuroot` lives beside the `.rehuco` files — by default the `.rehuco`'s own folder —
  and a `.rehuco` names it by a path relative to itself: `"roots": [ { "file": "tutorials.rehuroot" }, … ]`, format
  4. It is saved as the `.rehuco` is: under the lock, compared with what this machine last read, refused when another
  machine changed it meanwhile.
- **`id`** is the root's id, minted once and shared by every catalog that lists the file. **Mappings are therefore
  keyed by root id alone** — `{"format_version": 2, "roots": {"<root id>": {"path": …, "storage": …} | {"skipped":
  true}}}` — one mapping per root per machine, whichever catalogs list it. The cache stays per catalog (`<rehuco
  id>.rehudb`), so a root two catalogs share is scanned into both; a cache per root is the follow-up
  ([[appendices.open-questions#still-open]]), not this.
- **`layouts`** says where a record of each type lives under this root: a map from a resource type's main key, or
  `*` for any type not named, to a **path template** — the Locations grammar ([[plugins#tutorial-plugin]]'s
  placeholders, `{{ … }}` optional groups, `{count}` where the type declares it, the Location Replacements applied
  after) **plus `/` as a level separator**, each segment sanitized as a name is today and the separators kept. The
  value `*` means *keep the record's current folder name*, at the root's top. The default `{"*": "*"}` admits
  anything under its current name; `{"tutorial": "{authors}/{title}{{ [{year}]}}"}` groups tutorials under their
  authors **and admits no other type** — a type with no entry and no `*` cannot be moved here.
- **`fallbacks`** names what a placeholder renders as when the record leaves it empty. An empty placeholder outside
  an optional group with no fallback **forbids** the root for that record, and the renderer says why — the path row
  shows the root greyed with the reason ([[plugins#tutorial-plugin]]).
- **Adding a root** is picking existing `.rehuroot` files, or a folder, which makes one with a layout chosen from the
  default root layouts the settings keep ([[plugins#rehuco-dock]]); the Roots view edits a root's layouts and
  fallbacks beside its name.
- **Nothing is migrated**, as format 2 was not: a format-3 `.rehuco` is refused with a message saying to add its
  roots again, and a format-1 mapping file is set aside. Overlap is checked across the catalog's `.rehuroot`s as it
  was across its roots.

## §9.4 The node serves what its machine reaches

[[[mounts-and-storage#nodes-serve-mounted]]]

The node has no roots of its own ([[nodes#two-roles]]): it reads the user's `.rehuco` from the shared app folder and
serves every root this machine has a working mapping for — a local disk, a mounted share — plus its borrow store. A root
mapped but offline shows as offline on the web pages as it does in the agent; an unmapped one is not served.

## §9.5 The file notifier: one change source, and the catch-alls behind it

[[[mounts-and-storage#out-of-band]]]

- [#511: feat(core): FileNotifier — native events, an own SMB session for shares, polling as the floor](https://github.com/borco/rehuco/issues/511)

Every view in the app — the cache and its browsers, the Roots view, the Files dock, open documents — learns that
something on disk changed from **one source**, the `FileNotifier` in rehuco-core, publishing on the `ChangeFeed`
([[nodes#access-seam]]). Nothing announces its own writes to the others any more: a save, a screenshot written, a
checksum record, a change made by another machine or by hand reach the views by the same path, as what the disk says
happened. **One exception: a rename this machine runs** is published at once by the rename coordinator, with its exact
plan, so no holder keeps the old path while the notifier catches up; the notifier's own report of it arrives after and
finds nothing at its sources to move. The notifier runs per root, with a backend chosen by the mapping's storage kind,
measured in #502:

| Root on | Backend | Measured |
| --- | --- | --- |
| A local disk or removable drive | **Native events** (`watchdog`: ReadDirectoryChangesW, FSEvents, inotify), recursive | Ordinary on all three OSes |
| An SMB share | **Our own SMB session**: `smbprotocol` opens the root on a session of its own and waits on `CHANGE_NOTIFY` with the tree flag; the server answers from its inotify watches, so every writer on every client is seen. Data still flows through the OS mount; this session carries notifications only. | Complete against the TS-230, mini2 and esprimo: create, write, rename (an old-name/new-name pair), atomic replace, delete, ~5 ms after a local write, ~100 ms after another machine's; a 2000-file burst delivered in full. Needs the share's credentials: the Windows logon serves as is; on macOS and Linux the agent asks once and keeps them in the OS keychain. |
| A share without credentials, anything else, any backend that failed | **Polling** of the cache's known records by stat signature, on a timer | The floor, never the design: a stat per record over the LAN is 1–3 ms, so 10k records sweep in 10–30 s at a few minutes' interval. |

The OS client's own watcher on a share is **not** a backend: on Windows it works (ReadDirectoryChangesW is forwarded
to the server) but drops events under load with no overflow signal; on macOS FSEvents over SMB produced four nameless
"folder modified" events for a 500-file burst; on Linux `inotify` on `cifs` sees only this machine's writes.

Rules:

- **Events are debounced and coalesced** into the feed's `Changed`, `FolderChanged` and `Moved`; a rename's pair becomes
  one `Moved` with the executed plan — the `(source, destination)` pairs — and each holder applies *a path at or
  beneath a renamed source lands at the same offset beneath its destination* to everything it holds, which covers every
  scoping case ([[data-model#resource-scoping]]).
- **A notify-buffer overflow publishes `RootStale`** for that root, and every holder re-reads it as `F5` does — the
  root is scanned again. On a local disk, too: ReadDirectoryChangesW reports an overflow as a successful read of zero
  bytes, which `watchdog` passes over in silence, so the notifier reads that itself.
- **The notifier runs on a daemon thread and survives the mount dropping** ([[mounts-and-storage#offline-mounts]]): a
  backend that fails falls back to polling, which also says whether the root can be reached — published as
  `RootReachable`, and written into the cache — and the backend is tried again every 30 s while it can; once it is back,
  the root is `RootStale`, since a sweep finds only the records it knew. A root that cannot be reached keeps its rows in
  the browsers, greyed and not opened; browsing what is retained of it is [[mounts-and-storage#durable-retention]]'s.
- **The folder of a document opened from outside every root is watched too**, with the same backends: everything beneath
  a directory-scoped record's folder, a file-scoped one's folder alone, a folder already covered by another's watch not
  again.
- **A watch never holds a rename up.** Measured on NTFS with a live watch: a folder beneath the watched one renames, and
  so does the watched folder itself; only the watched folder's *parent* is refused, its handle being open beneath it. A
  root's watch therefore stands in no rename the app makes — it renames nothing above a root — though a rename of the
  folder holding a root, in Explorer, waits for the app to close. An open document's folder watch lets go for every
  directory rename and watches again once it is over. Samba holds no such lock: a share's session never refuses one.
- **Verify-on-access and the incremental scan stay as the catch-alls.** The cache stores each `.rehu`'s stat signature
  and content hash ([[data-model#scan-and-staleness]]); opening, browsing to or serving a resource re-checks it, and the
  version-aware incremental scan finds what no event and no visit did. A polled root relies on them.

**Browsing never blocks a rename.** A directory-scoped rename on NTFS fails while any handle is open beneath the
directory, so no browsing view or scan holds one between reads: every directory listing is one chunk under the rename
coordinator's hold, closed before the next, and yields when a rename asks (#241, #372, #378).

## §9.6 Progress follows the user, not a node

[[[mounts-and-storage#node-handoff]]]

A user may watch a tutorial in the agent, carry on from the tablet through a node, and come back. There is no handoff
between nodes to design: progress is written **every few seconds** (and on pause, seek and stop) into the user's
sidecar on the share ([[field-schema#watch-progress]], [[data-model#single-file]]), and every player reads it from
there before resuming — the agent directly, the web page through its node — so whoever picks it up is at most seconds
behind.

## §9.7 Example deployment: several machines on one share

[[[mounts-and-storage#example-deploy]]]

The PC, the Mac mini and a Linux box all mount the TS-230's share; each runs its agent over its own `.rehudb` and, while
its user is logged in, its node. **"Who serves a resource" needs no answer**: every machine reaches the files itself,
and the node a tablet talks to is the one its user chose ([[nodes#node-actions]]). The machine that travels takes its
borrowed copies along and serves them from its own node with everything at home switched off
([[borrowing#vacation-topology]]). The TS-230 runs nothing of rehuco's ([[packaging-deployment#ts230-as-nas]]).

**One thing several machines on one share cannot do: yield to each other's renames**
([#241](https://github.com/borco/rehuco/issues/241)). Within one process a rename asks the jobs reading beneath it to
close their handles, and they do so at the next chunk boundary — measured at ~7 ms. That request does not cross a
machine boundary: a directory rename issued on box A while box B reads inside it over SMB can be refused by the server,
for the one chunk in which B's handle is open. File-level operations are fine regardless — readers open sharing every
right including delete, so renaming or replacing *the file being read* succeeds from any machine, with one caveat
measured in #503: the macOS client keeps a closed file's handle for a while, so a replace from another machine right
after a Mac read may need a retry. The rename reports the refusal and offers to retry; there is no coordinator across
machines and none planned.

## §9.8 Configurable durable retention of offline-media metadata

[[[mounts-and-storage#durable-retention]]]

- [#405: docs: spec root caching, borrowing UI, and per-file watch progress](https://github.com/borco/rehuco/issues/405)

`.rehuco` can opt in, per root and per machine (it is in the mapping), to keeping a **durable local copy of that root's
metadata** — so a root whose medium sits in a drawer, or whose share is switched off (the library shelf,
[[borrowing#library-shelf]]), stays browsable. The UI calls this **caching a root**; the spec keeps *retention*,
because everywhere else here a cache is disposable and this copy is not (below).

- **Why**: offline media are painful to rescan one-by-one, and a switched-off NAS's content would otherwise drop out of
  the catalog. Retaining their metadata locally keeps them browsable while disconnected, and — because the retained
  copies are ordinary local files — keeps them present across a full cache rebuild
  ([[architecture-design#why-distributed]]).
- **A default by the detected storage kind**, nothing else to configure:

  | Root | Retention |
  | --- | --- |
  | Removable (USB stick, external drive, CD/DVD) | **Forced on** — removable by definition, so it must stay browsable without its medium |
  | Network share | **On by default**; the user may turn it off for a share known to stay online, where retaining only buys speed |
  | Local disk | Off — the disk is always there to read |

  It is per root, not per resource: keeping one resource *whole* on this machine is a borrow
  ([[borrowing#another-instance-role]]), not retention.
- **What is retained is enough to browse, never to watch.** Per resource: the `.rehu` itself, the user's own sidecar,
  its screenshots copied as they are, and its **file structure**: every file's relative path and size, plus each
  video's duration and resolution. That is what lets the browser, the Description View and the Files dock show an
  offline resource, read-only. No content file is copied; watching a resource whose source is offline needs a borrow.
- **Durable, not disposable.** A removable root cannot be rescanned while its medium is absent, so its retained copy is
  the only one there is. The store therefore sits beside `.rehudb` ([[data-model#local-file-trio]]), never inside it: a
  cache rebuild must not wipe it.
- **Per-user state for a source that can never be written** — a CD/DVD, a read-only share — is tracked on the retained
  copy, which stays writable for per-user data only ([[field-schema#watch-progress]]).
- **Retained copies are read-only stand-ins** for the details ([[offline-editing#overview]]); a per-user edit made
  against one is a queued save ([[sync#apply-payload]]).
- **Staleness is resolved by comparison, not blind overwrite.** When a retained source is reachable again, the notifier
  and verify-on-access re-pull only what moved ([[data-model#scan-and-staleness]]).

## §9.9 Tolerating offline mounts without blocking

[[[mounts-and-storage#offline-mounts]]]

An agent and its node run while the boxes whose shares they mount — the TS-230 in particular — are powered off or
unreachable for long stretches. A mapped root is therefore frequently **present in `.rehuco` but currently dead**, and
everything else must keep working without stalling on it.

The hazard is concrete: on a dead SMB/NFS mount, ordinary filesystem calls (`stat`, `open`, directory listing) **block
for the mount's timeout** — tens of seconds, or indefinitely with a hard mount — so code that naively touches a mounted
path wedges whatever thread it is on.

Rules:

- **Treat every mounted root as possibly-offline.** Reachability is runtime state, not config; never assume a mount is
  live because it is declared.
- **Probe reachability cheaply and out-of-band.** Check liveness with a single bounded-timeout operation (a `stat` of
  the mount root) on a worker, not on the GUI thread or a request path. Cache the up/down result and **back off**
  before re-probing, so a dead mount is consulted rarely and a flapping one causes no churn.
- **All mount I/O is timeout-wrapped and off the hot path.** File reads through a mount run on workers with their own
  deadlines, so one dead mount never blocks the window, a request, or another mount's traffic.
- **Offline ⇒ show last-known, read-only.** The browser shows the cached rows, the Roots view the retained structure
  ([[mounts-and-storage#durable-retention]]), with status `offline, showing last-known`; a save for a record there waits
  in the queue ([[sync#apply-payload]]).
- **Recovery is the notifier's, not a rescan's.** When a probe succeeds again the share's notification session is
  re-opened and verify-on-access catches up on what was touched meanwhile; the mount coming back forces no full rescan.

**The agent applies the same rules to what it remembers (#464).** At start, the recent files, the recent root catalogs
and the session's open documents are each judged *present*, *gone* or *offline* (`borco_core.path_presence`). A fixed
local drive is checked at once — it answers, so a missing file is gone. A share, a removable drive or a disc is
classified without touching it (the drive letter's type, the mount table), its server is asked with a 0.3 s connection
attempt rather than a `stat` (measured: a `stat` under a switched-off SMB host blocks **21 s**, the connection attempt
0.3 s), and only a server that answered is `stat`-ed. All of it runs on daemon threads, so neither the start nor the
quit waits for a dead mount. *Gone* is forgotten; *offline* is kept, shown disabled, and asked again next run.

*Limitation, accepted:* a session document kept open because its share was off is matched against what the user opens
by hand by its **resolved** path, while the session stores the path as it was opened. A path whose resolved form
changed between runs — a mapped drive now reached through its UNC path, a folder moved behind a symlink — is not
matched, so a document the user opened and then closed by that other spelling comes back open at the next start.

Deployment note: mount the shares **soft / with short timeouts** so failed syscalls return an error quickly rather than
hanging. Hard mounts defeat this discipline.

## §9.10 Fingerprint files

[[[mounts-and-storage#fingerprint-map]]]

Retired. Fingerprint files dropped into roots let nodes discover that two of them served one storage and how the paths
mapped. The `.rehuco`'s explicit **location** per root ([[mounts-and-storage#rehuco-scope]]), resolved through each
machine's mount table, answers the same question without writing anything into the user's folders.

## §9.11 Adding a root

[[[mounts-and-storage#folder-add]]]

Retired as a primary/remote declaration; there is no owner to declare ([[multiplicity#instances]]). Adding a root is:
pick the folder, detect its storage kind and its location from this machine's mount table, refuse it if it overlaps a
root already listed, write this machine's mapping ([[mounts-and-storage#rehuco-scope]]) — or, with
[[mounts-and-storage#rehuroot]], pick existing `.rehuroot` files, which already know their location.

## §9.12 Measuring a machine's throughput

[[[mounts-and-storage#node-benchmark]]]

Retired as a grading scheme that fed a dispatcher. The one decision it would have driven — where a checksum run
executes — is settled by locality instead: a node that reaches the root's disk locally may be handed the job
([[nodes#node-status]]). What remains is the checksum **algorithm** benchmark in rehuco-core's tests, which chose the
hash ([[data-model#checksums]]).

## §9.13 Verified copies and moves

[[[mounts-and-storage#safe-move-rename]]]

> [!NOTE]
> **Implement the cross-filesystem move with Opus, not the auto-switched Sonnet.** The copy → verify-checksum-on-target
> → delete-source-only-if-verified sequence is data-loss-sensitive: a wrong ordering or a skipped verification can
> delete the only good copy. Override to `/model opus` for the cross-FS path.

The system chooses *how* to perform a move/rename rather than assuming:

- A rename/move **within one filesystem** is a near-instant metadata operation, including over SMB, where the rename is
  server-side ([[packaging-deployment#ts230-as-nas]]).
- **Cross-filesystem moves are checksum-gated (hard rule):** verify the source against its checksum record → copy →
  verify the checksum on the *target* → delete the source **only if verification passes**. An interrupted move leaves
  the source untouched and the partial target resumable, so it never loses data.
- **The copy is resumable.** A verified copy that stops — the NAS switched off, the laptop closed — picks up from the
  bytes already on the target rather than starting over; this is what rsync would have bought, and the one thing it
  would have ([[appendices.post-mortem#architecture]]).

**One verified copy, three uses** (#339). The sequence is built as a reusable **verified copy**, and the moves and
borrows are made from it:

| Operation | Built as |
| --- | --- |
| Move to another filesystem | verified copy, then delete the source only if the target verified (#339) |
| Borrow onto a machine | verified copy into that machine's node's borrow store, no delete ([[borrowing#another-instance-role]]) |
| Return | verified copy back of what changed (the sidecars, possibly the record), then the copy is removed |

The bytes travel over the mounts, read by the machine doing the copy; a node with local access to one end may run the
verify there ([[nodes#node-status]]). The job records each end as a root and a root-relative path, never an absolute
path, so it survives restarts and a machine's remapping.
