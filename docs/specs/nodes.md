# §5. Node Communication

**Plain REST over HTTP**, not a message queue or pub-sub broker. The actual operations needed (query catalog, fetch content/thumbnails, push state sync, trigger a remote checksum job, notify a node that a file changed, serve a browser) are simple request/response patterns. A queue would add infrastructure (broker, persistence) with no real benefit at this scale, and would burden the weakest hardware (QNAP TS-230). REST is also natively browser-compatible, covering the tablet/web-UI case for free.

Nodes need to support, at minimum:

- Serving `.rehu`/catalog data (read)
- Accepting metadata/state updates (write, subject to ownership rules in §7)
- Accepting an async "please checksum these files and report back" job, pollable for progress
- Accepting a lightweight "re-read this specific resource, it changed" notification (§9.5)
- **Browsing the node's own local filesystem** (list directories/files) so the admin app can build folder selections against the *node's* reality, not the app's machine (§5.1, §9.10)
- Accepting and reporting **benchmark jobs** (§9.11) and **safe-move jobs** (§9.12)
- Dropping/creating **fingerprint files** and reporting found fingerprints for auto-mapping (§9.9)

## §5.1 Two roles: node (service) and agent (desktop GUI)

The thing loosely called "the app" or "the admin app" elsewhere is more precisely the **agent**. Two distinct *roles* exist, because one process cannot be both a headless server (on the QNAP, no display) and a GUI (PySide6, needs a display):

- **Node** — the headless service: HTTP server, swarm participation, serving data, running jobs. Runs on every participating machine *including* headless ones (QNAP). Never has a GUI.
- **Agent** — the desktop-only GUI: tray icon, viewer/editor windows, catalog/admin UI. It is a **node client** — it talks to a local (or remote) node over the same HTTP/socket interface everything else uses. On a headless machine there is a node and *no* agent.

On GUI desktops the node and agent usually ship together and feel like one tray app; on the QNAP the node runs alone. The key rule: **the node role must not depend on the agent role existing**, because on headless boxes it won't. "Admin" is a property of the **logged-in user**, not of the agent (§6.8) — the agent exposes admin functions only when an admin user is authenticated; there is no separate "admin build."

**Independent lifecycles.** Quitting the agent (the GUI) leaves the local node running — it's a service that should keep serving the swarm, the tablet, and other nodes even when the desktop GUI is dismissed (like closing a mail client's window while background sync continues). Stopping the node is a separate, more deliberate action (it takes that machine's content offline to the swarm). The node runs as a service/daemon or launch-on-login, independent of the tray.

**The agent is a node client for swarm operations** (catalog, per-user state, sync, anything access-controlled): it never reads/writes the catalog filesystem directly, so there is no "local path vs. remote node" dual code path — it always asks a node, which optimizes how to satisfy the request (own disk, mount, or delegating). The mount-vs-node access-route optimization (§9.2) lives entirely inside nodes. Editing a node's `.rehuco` browses *that node's* filesystem via the node's remote-browse capability (§5 list), not the agent's machine. (Exception: the bare single-file viewer needs no node at all — see §5.3.)

## §5.2 Readiness is per-operation, never one global gate

The app must be usable before swarm chatter settles. The mistake to avoid is a single `node_is_ready` flag that blocks everything until the slowest background task finishes. Instead, operations are tiered by what they actually depend on:

- **Local-file only** → never waits. Double-clicking a `.rehu` to view it reads that one self-describing file (and its sibling screenshots) off disk and renders immediately — no swarm, no registry, no cache, no login required.
- **Local cache** → waits only on the local `.rehudb` load (or shows results progressively as it loads), never on the network. Browsing/searching the catalog is stale-but-local until background sync refines it.
- **Current access rules** → the *only* tier the serve-after-resync gate (§6.11) blocks, and only for **serving access-controlled resources to a user**, and only when there is genuinely newer access data to catch up to (the version-marker check). A node that missed nothing, or a single node (§8.1), satisfies it instantly.

All swarm activity — discovery, registry resync, fingerprint mapping (§9.9), instance reconciliation, propagation — runs **async in the background** (in the task queue, §3) and surfaces *status* ("syncing" / "offline, showing last-known" / "up to date"), never a blocking splash. The app opens interactive on local/cached data and refines as sync lands.

## §5.3 Local-file mode vs. swarm mode

The agent operates in two scopes, and conflating them is what made §5.1's "always a node client" sound contradictory:

- **Local-file mode** — viewing/editing a *single* `.rehu` off disk. Needs **no node, no login, no swarm**. It just parses the self-describing file, shows/edits fields, renders the Markdown, reads/writes sibling screenshots. This is the "dumb viewer/editor" — and it's the correct behavior for a file the local node doesn't manage, a machine with no node installed, or a single `.rehu`+folder someone received.
- **Swarm mode** — the full catalog/admin experience. Node client, login, access-controlled, everything in §5.1.

**Local-file mode is the floor; swarm mode enriches when present.** Viewing/editing a local file is *not* an access-controlled operation — access control (§6.10) governs what a node serves over the network, and cannot govern a file the OS already lets the user read (the same "can't fight the device owner" logic as §6.11). So opening a local file requires no login at all. If the agent *does* have a session and recognizes the file's UUID as swarm-managed, it enriches the open view in place (per-user progress/notes, sync) — but enrichment lands as a non-blocking refinement (§5.2) and never delays the open. An edit made in local-file mode to a node-managed file is just a local write the node picks up via its change-notification/scan path (§9.5).

## §5.4 Single-instance behavior and file association

The agent uses the standard single-instance pattern: on launch (or `.rehu` double-click) it tries to bind a local socket; if it binds, it is the **main instance**; if the bind fails, another agent is already running, so it connects to that socket, forwards the file path, and exits — the main instance opens a new viewer view for the forwarded file. (This matches Qt's `QLocalServer`/single-application approach.)

- **One main instance hosts both scopes.** A forwarded double-click opens a local-file-mode view (§5.3, instant) regardless of whether the same instance also has a swarm-mode catalog window open. No separate viewer process.
- **Forwarded opens never block on login/sync.** The receiving instance opens the local file immediately and enriches only if it happens to be logged in and recognizes the UUID (§5.3).
- **Tray.** If tray mode is enabled, closing the window minimizes to tray and quit is explicit (tray menu / window menu); if disabled, closing quits. The tray lives on the **agent** (the only part with a GUI); quitting it does not stop the local **node** (§5.1).
- **Robustness:** if bind fails *and* connect also fails, assume a crashed holder left a stale socket — reclaim it and become the main instance. The socket name must be **scoped per OS user and per swarm**, so separate users or side-by-side swarms (§8) don't collide on one socket and forward to the wrong instance.
- **Platform mechanics live in §16.8.** How each OS delivers a double-clicked `.rehu` into the running instance — and the file-association and app-identity registration it needs — is OS-specific and is covered under packaging (§16.8).
