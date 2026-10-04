# §5. Node Communication

[[[nodes]]]

## Overview

[[[nodes#overview]]]

**Plain REST over HTTP**, not a message queue or pub-sub broker. The actual operations needed (query catalog, fetch
content/thumbnails, push state sync, trigger a remote checksum job, notify a node that a file changed, serve a browser)
are simple request/response patterns. A queue would add infrastructure (broker, persistence) with no real benefit at
this scale, and would burden the weakest hardware (QNAP TS-230). REST is also natively browser-compatible, covering the
tablet/web-UI case for free.

**One HTTPS API for everything, not HTTP for the web and RPC between nodes** (#409): FastAPI over HTTP/2, JSON bodies,
server-sent events for streams, and plain HTTP Range for media. An RPC channel beside it was considered and rejected:

- **Not more secure.** Transport security is the same mutual TLS with device-ID pinning either way
  ([[discovery-trust-access#node-identity-pairing]]); a second protocol is a second listener, a second auth path and a
  second parser to get right. The separation that matters — node and agent routes versus the web UI — is done by the
  trust model on one API ([[discovery-trust-access#remote-admin]]).
- **Not meaningfully more efficient.** The bottleneck is disk, SMB and network bandwidth; heavy work runs on the node
  that owns the files, so the wire carries small metadata, rows and progress writes. Video needs HTTP anyway —
  libvlc and the browser's `<video>` play an HTTP URL with Range.
- **Ruled out outright:** pickle- or object-proxy RPC (RPyC, Pyro) executes what it is sent; Qt Remote Objects ships
  in `PySide6-Addons`, which the agent dropped (#211), and the node has no Qt.

The transport is confined to the remote access client and the shared wire schema ([[nodes#access-seam]]), so changing
it later replaces one layer, not the code above it.

Nodes need to support, at minimum:

- Serving `.rehu`/catalog data (read)
- Accepting metadata/state updates (write, subject to ownership rules in [[sync#overview]])
- Accepting an async "please checksum these files and report back" job, pollable for progress
- Accepting a lightweight "re-read this specific resource, it changed" notification ([[mounts-and-storage#out-of-band]])
- **Browsing the node's own local filesystem** (list directories/files) so the admin app can build folder selections
  against the *node's* reality, not the app's machine ([[nodes#two-roles]], [[mounts-and-storage#folder-add]])
- Accepting and reporting **benchmark jobs** ([[mounts-and-storage#node-benchmark]]) and **safe-move jobs**
  ([[mounts-and-storage#safe-move-rename]])
- Dropping/creating **fingerprint files** and reporting found fingerprints for auto-mapping
  ([[mounts-and-storage#fingerprint-map]])
- Accepting an **image-scan job** for a resource it can reach, and accepting **scan results posted back** by
  another node for a resource it owns — the primary alone writes the sidecar ([[reference-images#dispatch]])

## §5.1 Two roles: node (service) and agent (desktop GUI)

[[[nodes#two-roles]]]

The thing loosely called "the app" or "the admin app" elsewhere is more precisely the **agent**. Two distinct *roles*
exist, because one process cannot be both a headless server (on the QNAP, no display) and a GUI (PySide6, needs a
display):

- **Node** — the headless service: HTTP server, swarm participation, serving data, running jobs. Runs on every
  participating machine *including* headless ones (QNAP). Never has a GUI.
- **Agent** — the desktop-only GUI: tray icon, viewer/editor windows, catalog/admin UI. It reaches a root no node owns
  directly through rehuco-core, and goes through the owning node for every root a node owns — on this machine or
  another — and for what crosses machines (below, #409). On a headless machine there is a node and *no* agent.

Both are **thin hosts over rehuco-core**: the reading, writing, scanning, checksumming and probing live in the Qt-free
library, and the agent and the node only wire it up — one with a GUI, the other with an HTTP server. New logic lands
in core, taking paths, settings and the username as parameters, so a node can do whatever the agent does without the
code moving. The key rule stays: **the node role must not depend on the agent role existing**, because on headless
boxes it won't. "Admin" is a property of the **logged-in user**, not of the agent
([[discovery-trust-access#user-auth]]) — the agent exposes admin functions only when an admin user is authenticated;
there is no separate "admin build."

**What the agent asks a node for.** A root **no node in the agent's current swarm owns**, the agent reaches itself —
no HTTP, its own `.rehudb`. It goes through a node for:

- **Every root a node owns — wherever that node runs.** On another machine (a disk, or a share only that node
  mounts) and **on this machine too**, including a node the agent hosts itself: catalog, viewing, playback, edits and
  jobs all go through the owning node, by the access seam ([[nodes#access-seam]]), so the node stays the one writer
  of its files ([[data-model#write-integrity]]) and the one cache of its roots — the agent does not scan them into its
  own `.rehudb` as well. While that node is not running, edits to its roots are refused with the reason, and a hosted
  node can be restarted from there; reads it can't answer show as unreachable.
- **The web UI**, which a node serves ([[borrowing#vacation-topology]]).
- **Progress and per-user state** following the user to the watch node and back ([[field-schema#watch-progress]]).
- **Borrowing** ([[borrowing#agent-ui]]) and **moves between nodes** ([[mounts-and-storage#safe-move-rename]]).
- **Managing nodes**: the local one, and any paired node for an admin user — add, remove, start, stop, configure
  ([[discovery-trust-access#remote-admin]]).

Editing a node's `.rehuco` browses *that node's* filesystem via the node's remote-browse capability
([[nodes#overview]] list), not the agent's machine.

**Two ways to host a node — the user's choice, and nodes come and go.**

- **Hosted by the agent.** A setting, *Run a node while rehuco is running*, sits beside the tray setting and is
  independent of it; it is off by default. The agent starts the node as a **child process** — the same `rehuco-node`
  as a standalone one, so one code path, no Qt and asyncio sharing an event loop, and a crash in either leaves the
  other standing — and stops it on quit. Simplest for one person's swarm on a PC that is not always on.
- **Installed as a service** (launch-on-login or a system service), independent of the agent: quitting the GUI leaves
  it serving the swarm, the tablet and other nodes, like a mail client's window closing while sync continues. The
  shape for an always-on box or a family swarm. The agent manages it like any remote node.

| Tray | Hosted node | Behaviour |
| --- | --- | --- |
| off | off | No network; closing the window quits |
| on | off | Closing the window hides to the tray |
| off | on | The node lives exactly as long as the window |
| on | on | Closing the window keeps the node serving; Quit stops both |

Either way a node may be absent at any moment — a PC switched off, a hosted node quit with its agent — and the swarm
already treats that as ordinary ([[nodes#readiness-per-op]], [[mounts-and-storage#offline-mounts]]). Anything that
needs a node *on this machine* — borrowing onto it, serving the web UI from it — needs one of the two running here.
(The bare single-file viewer needs no node at all — see [[nodes#local-vs-swarm]].)

## §5.2 Readiness is per-operation, never one global gate

[[[nodes#readiness-per-op]]]

The app must be usable before swarm chatter settles. The mistake to avoid is a single `node_is_ready` flag that blocks
everything until the slowest background task finishes. Instead, operations are tiered by what they actually depend on:

- **Local-file only** → never waits. Double-clicking a `.rehu` to view it reads that one self-describing file (and its
  sibling screenshots) off disk and renders immediately — no swarm, no registry, no cache, no login required.
- **Local cache** → waits only on the local `.rehudb` load (or shows results progressively as it loads), never on the
  network. Browsing/searching the catalog is stale-but-local until background sync refines it.
- **Current access rules** → the *only* tier the serve-after-resync gate ([[discovery-trust-access#serve-after-resync]])
  blocks, and only for **serving access-controlled resources to a user**, and only when there is genuinely newer access
  data to catch up to (the version-marker check). A node that missed nothing, or a single node
  ([[multiplicity#single-node-base]]), satisfies it instantly.

All swarm activity — discovery, registry resync, fingerprint mapping ([[mounts-and-storage#fingerprint-map]]), instance
reconciliation, propagation — runs **async in the background** (in the task queue, [[architecture-design#components]])
and surfaces *status* ("syncing" / "offline, showing last-known" / "up to date"), never a blocking splash. The app opens
interactive on local/cached data and refines as sync lands.

## §5.3 Local-file mode vs. swarm mode

[[[nodes#local-vs-swarm]]]

The agent operates in two scopes (an earlier "the agent is always a node client" made them sound contradictory;
since #409 the agent goes through a node only for roots a node owns):

- **Local-file mode** — viewing/editing a *single* `.rehu` off disk. Needs **no node, no login, no swarm**. It just
  parses the self-describing file, shows/edits fields, renders the Markdown, reads/writes sibling screenshots. This is
  the "dumb viewer/editor" — and it's the correct behavior for a file the local node doesn't manage, a machine with no
  node installed, or a single `.rehu`+folder someone received.
- **Swarm mode** — the full catalog/admin experience: local roots directly, other nodes' roots through them, login and
  access control for what nodes serve — everything in [[nodes#two-roles]].

**Local-file mode is the floor; swarm mode enriches when present.** Viewing/editing a local file is *not* an
access-controlled operation — access control ([[discovery-trust-access#access-control]]) governs what a node serves over
the network, and cannot govern a file the OS already lets the user read (the same "can't fight the device owner" logic
as [[discovery-trust-access#serve-after-resync]]). So opening a local file requires no login at all. If the agent *does*
have a session and recognizes the file's UUID as swarm-managed, it enriches the open view in place (per-user
progress/notes, sync) — but enrichment lands as a non-blocking refinement ([[nodes#readiness-per-op]]) and never delays
the open.

**Saving is where managed files converge back ([[data-model#write-integrity]]).** If the agent has a session and the
file's owning node is reachable (the same check that powers enrichment), the save routes through that node like any
swarm edit, honoring the single-writer rule. Otherwise the agent writes the file directly — local-file mode stays fully
usable as the floor — and the write is an **out-of-band change**: the owning node detects it via verify-on-access
([[data-model#scan-and-staleness]]) the next time the resource is opened, browsed, or served (or at the next incremental
scan) and reintegrates it then ([[mounts-and-storage#out-of-band]]). Atomic writes ([[data-model#write-integrity]])
bound the residual race to lose-one-never-corrupt; the version-vector comparison decides fast-forward vs.
genuinely-concurrent ([[data-model#write-integrity]], [[sync#overview]]).

## §5.4 Single-instance behavior and file association

[[[nodes#single-instance]]]

The agent uses the standard single-instance pattern: on launch (or `.rehu` double-click) it tries to bind a local
socket; if it binds, it is the **main instance**; if the bind fails, another agent is already running, so it connects to
that socket, forwards the file path, and exits — the main instance opens a new viewer view for the forwarded file. (This
matches Qt's `QLocalServer`/single-application approach.)

- **One main instance hosts both scopes.** A forwarded double-click opens a local-file-mode view
  ([[nodes#local-vs-swarm]], instant) regardless of whether the same instance also has a swarm-mode catalog window open.
  No separate viewer process.
- **Forwarded opens never block on login/sync.** The receiving instance opens the local file immediately and enriches
  only if it happens to be logged in and recognizes the UUID ([[nodes#local-vs-swarm]]).
- **Tray.** If tray mode is enabled, closing the window minimizes to tray and quit is explicit (tray menu / window
  menu); if disabled, closing quits. The tray lives on the **agent** (the only part with a GUI). Quitting it stops a
  node the agent hosts, never a node installed as a service; the tray and the hosted-node setting are independent
  ([[nodes#two-roles]]).
- **Robustness:** if bind fails *and* connect also fails, assume a crashed holder left a stale socket — reclaim it and
  become the main instance. The socket name must be **scoped per OS user and per swarm**, so separate users or
  side-by-side swarms ([[multiplicity#overview]]) don't collide on one socket and forward to the wrong instance.
- **Platform mechanics live in [[packaging-deployment#app-identity]].** How each OS delivers a double-clicked `.rehu`
  into the running instance — and the file-association and app-identity registration it needs — is OS-specific and is
  covered under packaging ([[packaging-deployment#app-identity]]).

## §5.5 The resource access seam

[[[nodes#access-seam]]]

- [#409: docs: access seam, owning-node rule, views, node hosting and instances](https://github.com/borco/rehuco/issues/409)

Some roots are reachable only through the node that owns them — a disk on another box, or a share only that box
mounts. To make their resources behave like local ones — browsed, viewed, played and edited from the agent — every
operation on a resource's files goes through **one operation-level interface in rehuco-core**, `ResourceAccess`, with
a local implementation and a remote one. The agent and the node both use the local one; the agent uses the remote one
for a node's roots. Status: decided, built from #413 on.

**Keys, not paths.** A resource is identified by a `ResourceKey`:

- `LocalKey(path)` — the resolved absolute path, so a local root maps to a key at no cost.
- `NodeKey(node_id, root_id, relative)` — a root of another node, and the path under it; the owning node resolves it
  to its own `LocalKey`. The `.rehudb` cache already stores resources as root plus root-relative path
  ([[data-model#cache-schema]]), so its rows map straight onto it.

A key is a **location**, not an identity: recognizing one resource reached by two routes stays a UUID question
([[mounts-and-storage#uuid-not-paths]]). Only a `LocalKey` exposes a path, so code that would treat a remote resource
as a file does not type-check.

**Operations, not bytes.** The interface is built from small groups — records (load, save, `record_progress`, legacy
conversion), a resource's file listing, screenshots (scan, read, reorder, convert, acquire, remove), content images
(enumerate, read one member, a playback source), jobs, mutations (rename, delete), and the catalog (roots, query,
row) — plus **capabilities** (a local path, reveal, the Recycle Bin, legacy conversion) that the UI turns features off
by, and a Qt-free **change feed**. There is no generic `open`: heavy work — checksums, measuring, scans, copies — is a
**job** that runs on the node that owns the files, in that node's own task queue, and the agent only shows its
progress. Reading one image or archive member is a single call returning bytes.

**Saving is a read-merge-write with a version check.**

- Every save re-reads the file under a per-file lock, takes the caller's resource metadata, keeps the file's current
  per-user maps, merges the caller's own user's fields, and writes atomically. On a node-owned root only the node
  saves, so the lock serializes that node's own writers ([[data-model#write-integrity]]).
- A save carries the `RecordVersion` it was edited from. The version covers the **non-user part only**, so a progress
  write every few seconds never fails a metadata save; only a newer metadata edit does, and that is reported as a
  conflict (Reload / Overwrite) instead of silently overwritten. Over the network the same check is an HTTP
  precondition, answered `409` on conflict.
- `record_progress` needs no version: it replaces one user's progress entry and nothing else
  ([[field-schema#watch-progress]]).
- Metadata edits go only to the node that owns the resource — the single writer of [[sync#overview]]. The username of
  a per-user write comes from the authenticated session, never from the request.

**Playback** asks for a source: a local path for a root no node owns, otherwise the owning node's answer — a signed,
short-lived media URL served with HTTP Range (the node may answer a client on its own machine with the file's path,
which plays without copying through HTTP). The in-app player, an external VLC and the web UI's `<video>` all play
what they are given.

**A hosted node needs no login from its own agent.** The agent that starts a node as its child process gives it a
machine-local token for that session, so working through one's own PC's node asks for nothing; a service node, or
any other machine's node, takes a normal login ([[discovery-trust-access#remote-admin]]).

**Changes.** A local implementation announces every change it makes on the change feed, which the agent's
`ResourceEvents` adapts to Qt signals. A node keeps a numbered **change journal** — its own changes and any
out-of-band change verify-on-access or a scan finds ([[mounts-and-storage#out-of-band]]) — served as server-sent
events; a client that reconnects after a gap invalidates that node's roots and refreshes, as F5 does.

**Never on the GUI thread.** The interface blocks, and a remote call is a network round trip, so the agent calls it
only from workers.

**One transport, confined.** The remote implementation and the node's HTTP layer share one wire schema in core, and a
contract suite runs the same tests against the local implementation and through HTTP to it, so the two cannot drift
([[nodes#overview]] for why HTTPS).
