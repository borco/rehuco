# §5. The Node

[[[nodes]]]

## Overview

[[[nodes#overview]]]

The node is **what the share cannot do**. Reading, writing, copying and watching the files are the operating system's
and the SMB server's job ([[architecture-design#why-distributed]]); the node adds, for the user whose agent runs it:

- **Web pages** for a tablet or a browser: the tutorial list, a watch page that plays a video over HTTP with Range and
  writes progress into the user's sidecar ([[field-schema#watch-progress]]), the image browser later.
- **Long jobs** run where the agent would otherwise block: checksum runs, verified copies, and, as an optimisation only,
  content hashing for a root whose disk is local to the node's machine ([[nodes#node-status]]).
- **The borrow store**: the folder borrowed copies live in, with their `.borrow` records ([[borrowing]]).
- **Discovery and login**: the node advertises itself over mDNS to agents on the LAN; a browser gets a plain URL. A
  user logs in to the web pages with a one-time password the node's CLI issues for that username, with a role
  ([[discovery-trust-access#user-auth]]).

**What it is today** (#506): a process the agent starts a few seconds after its window is up and stops when it quits,
running as the agent's user, that writes a heartbeat file and a log under the folder the two share
([[packaging-deployment#app-folders]]). *Settings* > *System Integration* turns it on and off and shows whether it runs;
the status bar's right end says *Local Node: Running* or *Stopped*. Everything above lands on that lifecycle.

**One HTTPS API for the web pages, when they come**: FastAPI, JSON bodies, plain HTTP Range for media. Spiked before
any page is written (#418, #419). There is no node-to-node protocol: nodes do not talk to each other, and nothing of
the catalog travels over it — an agent reads the files over its own mount.

**No system service, for now.** A node that serves from the login screen would have to run as a system service under
its own account on every OS; the Windows leg of #504 measured what that costs — a service sees none of the users'
mounts and credentials, cannot run from a per-user install, must be granted its way into profile folders. The owner
decided the node runs as the current user instead: it serves only while that user is logged in, and that is fine.
A service stays a possible later opt-in, with the recipe recorded on #504.

## §5.1 Two roles: agent (desktop GUI) and node (its child)

[[[nodes#two-roles]]]

Two distinct *roles* exist, because a GUI and a server are different processes with different lifetimes:

- **Agent** — the desktop GUI: tray icon, viewer/editor windows, the catalog and the settings. It reads and writes
  every file itself, over this machine's mounts, through rehuco-core.
- **Node** — the headless process the agent hosts. It has **no roots of its own**: roots are the user's, declared in
  the `.rehuco` ([[mounts-and-storage#rehuco-scope]]); the node reads the same per-machine app folder the agent uses
  and serves whatever of the user's roots is reachable from this machine, plus its borrow store. On the machine that
  travels, the NAS roots are offline mounts and the borrow store is local, so the node serves the borrowed tutorials
  with everything else switched off, with no configuration of its own.

Both are **thin hosts over rehuco-core**: the reading, writing, scanning, checksumming and probing live in the Qt-free
library, and the agent and the node only wire it up — one with a GUI, the other with an HTTP server. New logic lands
in core, taking paths, settings and the username as parameters, so the node can do whatever the agent does without
the code moving. "Admin" is a property of the **logged-in web user**, not of the agent
([[discovery-trust-access#user-auth]]).

**How the node is hosted.** The agent starts `rehuco-node` as a **child process** (`NodeHost`, over `QProcess`) on a
timer a few seconds after the window is up, so opening a file never pays for it; it holds the child's stdin, and the
node stops when that pipe reaches EOF — an agent that quits, or crashes, takes its node down with it and never leaves
an orphan. Quitting stops the node first thing once the close guards pass, with a short grace; a node still starting
is killed rather than waited for. The packaged app hosts the node as itself: `rehuco-agent --node` runs the node's own
`main`, so there is no second executable to ship. The node runs as the agent's user, and so sees that user's mounts,
credentials and profile folders with no elevation and no stored password.

| Tray | Node | Behaviour |
| --- | --- | --- |
| off | off | Closing the window quits |
| on | off | Closing the window hides to the tray |
| off | on | The node lives exactly as long as the window |
| on | on | Closing the window keeps the node serving; Quit stops both |

**One node per box.** A second user on the same machine runs their own agent and so their own node, on another port
and under another mDNS name, only while logged in ([[multiplicity#overview]]).

## §5.2 Readiness is per-operation, never one global gate

[[[nodes#readiness-per-op]]]

The app must be usable before anything in the background settles. The mistake to avoid is a single "ready" flag that
blocks everything until the slowest background task finishes. Operations are tiered by what they actually depend on:

- **Local-file only** → never waits. Double-clicking a `.rehu` to view it reads that one self-describing file (and its
  sibling screenshots and the user's sidecar) off disk and renders immediately — no catalog, no notifier, no node.
- **Local cache** → waits only on the local `.rehudb` load (or shows results progressively as it loads). Browsing and
  searching the catalog is stale-but-local until the notifier and the next scan refine it.
- **The share** → a save, a rename or a scan that needs the share waits for the share, as a job in the task queue
  that says so, never as a frozen window ([[mounts-and-storage#offline-mounts]]).

The notifier, the catalog's verify-on-access and the node's start all run **async in the background** and surface
*status* ("offline, showing last-known", "node starting"), never a blocking splash.

## §5.3 Local-file mode and the catalog

[[[nodes#local-vs-swarm]]]

The agent operates in two scopes:

- **Local-file mode** — viewing/editing a *single* `.rehu` off disk. Needs **no catalog, no node, no login**. It parses
  the self-describing file, shows/edits fields, renders the Markdown, reads/writes sibling screenshots and the user's
  sidecar. This is the "dumb viewer/editor" — the correct behavior for a machine with nothing configured, or a single
  `.rehu`+folder someone received.
- **Catalog mode** — a `.rehuco` is open: its roots are scanned into the `.rehudb`, the browsers and the Roots view
  show them, the notifier keeps them current, the node serves what it can reach.

**Local-file mode is the floor; the catalog enriches when present.** Viewing or editing a file the OS lets the user read
is never gated by a login: the web pages' access control ([[discovery-trust-access#access-control]]) governs what the
node serves over the network, and cannot govern a file the user already has.

**Saving is the same in both scopes** ([[sync#overview]]): the save takes the record's lock file, re-reads the file,
compares it with the version the edit was based on, merges the per-user fields, writes atomically and releases. Two
agents on one share, a web user writing progress through the node, and someone editing the file by hand are all kept
apart by that one rule, and a change that cannot be merged is a conflict the user resolves, never a silent overwrite.

## §5.4 Single-instance behavior and file association

[[[nodes#single-instance]]]

The agent uses the standard single-instance pattern: on launch (or `.rehu` double-click) it tries to bind a local
socket; if it binds, it is the **main instance**; if the bind fails, another agent is already running, so it connects to
that socket, forwards the file path, and exits — the main instance opens a new viewer view for the forwarded file. (This
matches Qt's `QLocalServer`/single-application approach.)

- **One main instance hosts both scopes.** A forwarded double-click opens a local-file-mode view
  ([[nodes#local-vs-swarm]], instant) regardless of whether the same instance also has a catalog open. No separate
  viewer process.
- **Forwarded opens never block.** The receiving instance opens the local file immediately.
- **Tray.** If tray mode is enabled, closing the window minimizes to tray and quit is explicit (tray menu / window
  menu); if disabled, closing quits. The tray lives on the **agent** (the only part with a GUI). An accepted close
  always quits the application explicitly, whether or not a tray icon exists: Qt's own last-window quit cannot be
  relied on, because a floating dock window is a top-level window of its own and its close is one QtAds only hides
  (#507). Hiding to the tray takes every floating dock window along and brings it back.
- **Robustness:** if bind fails *and* connect also fails, assume a crashed holder left a stale socket — reclaim it and
  become the main instance. The socket name is **scoped per OS user**, so two users on one box don't collide on one
  socket and forward to the wrong instance. A run with its own settings folder ([[packaging-deployment#app-folders]])
  takes a name of its own too, from that folder's path, so a development build never forwards to the installed one
  (#494).
- **Platform mechanics live in [[packaging-deployment#app-identity]].** How each OS delivers a double-clicked `.rehu`
  into the running instance — and the file-association and app-identity registration it needs — is OS-specific and is
  covered under packaging.

## §5.5 The record and catalog operations in core

[[[nodes#access-seam]]]

- [#413: refactor(core): resource keys, key relocation, an access router and a change feed](https://github.com/borco/rehuco/issues/413)
- [#416: refactor: records through the access seam — load, save with a version check, revert, convert](https://github.com/borco/rehuco/issues/416)
- [#417: refactor: the Root Catalog through the access seam — roots, queries, rows, scans](https://github.com/borco/rehuco/issues/417)

Every operation on a resource's files goes through a few **operation-level classes in rehuco-core**, Qt-free, that the
agent and the node both use: `LocalRecords` (load, save, `record_progress`, legacy conversion), `LocalCatalog` (roots,
query, row, count, follow a rename, refresh a record), and the `ChangeFeed` the notifier publishes on. They were built
in #413–#417 as the local half of a *remote access seam* — a `ResourceAccess` protocol with a `NodeKey`, an
`AccessRouter`, capability flags and five empty operation groups waiting for a remote implementation. The remote half
is **not coming**: a node is one more client of the share, and reaches the files the same way. The scaffolding goes in a
teardown (#509's follow-up), and what stays is this:

**Keys, not paths, where the cache speaks.** A resource is identified by a `LocalKey`: the absolute path, never
resolved, which would touch the disk; compared as its `Path` does — `os.path.normcase`'s rule, case folded on Windows,
kept on POSIX. The `.rehudb` cache stores resources as root plus root-relative path ([[data-model#cache-schema]]), and
the node addresses what it serves the same way, so neither depends on a drive letter. A key is a **location**, not an
identity: recognizing one resource reached by two routes stays a UUID question ([[mounts-and-storage#uuid-not-paths]]).

**Saving is a read-merge-write with a version check, under the record's lock** ([[sync#overview]] has the lock):

- Every save re-reads the file, takes the caller's resource metadata, merges the per-user maps **field by field**, and
  writes atomically. A per-user field the caller changed since it read the file is the caller's; every other one is
  the file's. The caller may change fields only in its own scope and the reserved `public` one, so another user's
  state, and `unknown`'s, is always the file's.
- A save carries the `RecordVersion` it was edited from: a hash of the **non-user part**, of the file, and of each
  per-user field as read, which is what tells a field the caller changed from one it merely still holds. A block
  holding nothing but its `users` map is not metadata. So a progress write every few seconds never fails a metadata
  save; only a newer metadata edit does, and that is reported as a conflict instead of silently overwritten. Only a
  refused save shows anything: the agent lists every value the two disagree on — the details, and the per-user fields
  of the caller's own scope and `public` — each with its original value, the caller's and the file's as three radios,
  a value that differs from the original in bold, started on the side that changed. It saves the picks, or discards
  the caller's edits; Save is disabled while every pick is the file's value, since that save would write the file
  back as it is.
- `record_progress` needs no version: it replaces one user's progress entry and nothing else
  ([[field-schema#watch-progress]]).
- With the per-user sidecar ([[data-model#single-file]]) the per-user half of this moves to a file that has one writer
  per user; the conflict dialog gains a second diff source and keeps its rows.

**The catalog group reads; its owner keeps it current.** `LocalCatalog` answers what a client asks of a catalog —
`roots()`, `query(CatalogQuery)`, `row(key)`, and `count(root)` for Remove Root's question. The two listings raise
`CatalogUnreadable` where a cache would raise `sqlite3.Error`, so no caller catches a driver's exception; a row or a
count that cannot be read answers nothing, logged. How a cache is opened, reconciled to the `.rehuco`'s roots and
followed through renames and saves is its own. Each call opens the cache for its own duration on the calling thread, so
any worker may call it. Scans and removing a root's rows are jobs.

**Changes come from the notifier.** The `ChangeFeed` carries `Moved`, `Changed`, `FolderChanged` and `RootStale`; the
agent's `ResourceEvents` adapts it to Qt signals, marshalled to the GUI thread. The notifier publishes what the disk
says ([[mounts-and-storage#out-of-band]]); a writer's own change reaches it the same way everyone else's does.

**Never on the GUI thread.** The classes block on storage, so the agent calls them only from workers.

## §5.6 Node actions in the agent

[[[nodes#node-actions]]]

- **Open local node** is always present: it starts the node if it is not running and opens its URL in the browser.
- One optional **remote serving node** setting, picked from the mDNS list or typed; **Open remote node** is enabled only
  when it is set. The tablet uses whichever node's URL the user hands it ([[borrowing#vacation-topology]]).
- **Borrow target preference**: local, the remote serving node, or both when both are reachable; a toolbutton menu on
  *Borrow* overrides it per borrow ([[borrowing#agent-ui]]).

## §5.7 What a node reports

[[[nodes#node-status]]]

A node is a multi-user, multi-job host, and the agent's **Nodes** view shows what each reachable node is doing:
copying, hashing, verifying, serving web sessions, with per-job progress, beside its CPU use and free memory. An
**admin** sees every user's jobs; a regular user sees only their own. The node's queue therefore runs jobs for several
users in parallel (one lane per user at least, heavy I/O serialized per volume), where the agent's own `TaskQueue` is
strictly serial ([[appendices.task-queue]]).

**Hash delegation, an optimisation only.** A node advertises the root ids it reaches on *local* disk. Content checksums
— the heavy `.checksum` runs over videos and archives, and the destination-side verify of a copy — may be handed to such
a node, which runs them on its own queue and writes the `.checksum` record beside the resource as any client would; the
agent learns of it through the notifier. The small `.rehu` hash a save compares is never delegated. With the TS-230 as
NAS-only, the gain exists for roots on a PC's own disks, not for the NAS itself.
