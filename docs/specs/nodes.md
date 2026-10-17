# §5. The Node

[[[nodes]]]

## Overview

[[[nodes#overview]]]

The node is **what the share cannot do**. Reading, writing, copying and watching the files are the operating system's
and the SMB server's job ([[architecture-design#why-distributed]]); the node adds, for the user whose agent runs it:

- **Web pages** for a tablet or a browser: the tutorial list, a watch page that plays a video over HTTP with Range,
  converting it first when the browser cannot play it ([[nodes#web-playback]]), and writes progress into the user's
  sidecar ([[field-schema#watch-progress]]), the image browser later.
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

**One HTTPS API for the web pages, when they come**: FastAPI, JSON bodies, plain HTTP Range for media, a self-signed
certificate; the pages are server-rendered with HTMX and Pico ([[nodes#web-pages]]). Both the stack (#418) and playback
(#419, [[nodes#web-playback]]) were spiked before any page was written. There is no node-to-node protocol: nodes do not
talk to each other, and nothing of the catalog travels over it — an agent reads the files over its own mount.

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
- [#510: refactor: tear down the remote access seam — NodeKey, AccessRouter, ResourceAccess, Capability, the empty op groups](https://github.com/borco/rehuco/issues/510)

Every operation on a resource's files goes through a few **operation-level classes in rehuco-core**, Qt-free, that the
agent and the node both use: `Records` (load, save, `record_progress`, legacy conversion), `Catalog` (roots, query,
row, count, follow a rename, refresh a record), and the `ChangeFeed` the notifier publishes on. They were built, in
issues #413–#417, as `LocalRecords` and `LocalCatalog`, the local half of a *remote access seam* — a `ResourceAccess`
protocol with a `NodeKey`, an `AccessRouter`, capability flags and five empty operation groups waiting for a remote
implementation. The remote half was **not coming**: a node is one more client of the share, and reaches the files the
same way. #510 tore the scaffolding down and dropped the `Local` prefix it no longer contrasted with: the main window
holds one `Records` and one `Catalog` directly, every key is a `ResourceKey`, and the feed's `Invalidated` became
`RootStale`. What stayed is this:

**Keys, not paths, where the cache speaks.** A resource is identified by a `ResourceKey`: the absolute path, never
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

**The catalog reads; its owner keeps it current.** `Catalog` answers what a client asks of a catalog —
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
agent learns of it through the notifier. The small `.rehu` hash a save compares is never delegated.

**What a node may do is the admin's call, per node.** A node's config carries a permission set — serve pages and
media, transcode, hash, verify copies, hold a borrow store — that it advertises with its reachable roots; hashing is
off until someone has looked at the numbers. The Nodes view offers a **Benchmark** action that hashes a fixed sample
from a root the node reaches and reports MB/s, the CPU load during the run and the time a typical pack would take; the
node stores the result with its date and shows it in its row. Delegation considers only nodes that allow the job kind,
prefers the best stored benchmark, and always falls back to the agent itself. A slow node is a scheduling matter, not a
speed one: its queue runs hashing at low priority, inside a time window, and pauses it while the node serves a video,
so a checksum sweep every few months is acceptable on a box that would be hopeless for daily hashing. One such box is
the TS-230 itself: a Debian container on it runs the node beside the data with plain inotify seeing every SMB writer,
on four slow cores; a headless node like that is given the user's `.rehuco` path and its machine name as config, since
no agent shares an app folder with it.

## §5.8 Playing a video in a browser

[[[nodes#web-playback]]]

- [#419: spike: video playback and resume on the iPad over the LAN](https://github.com/borco/rehuco/issues/419)
- [#433: feat(node): media with Range — `/media/<root_id>/<relative>` for `<video>`, VLC and the in-app player](https://github.com/borco/rehuco/issues/433)
- [#441: feat(web): watch a tutorial in the browser — resume, progress, viewed](https://github.com/borco/rehuco/issues/441)

Measured by the playback spike (#419) on an iPad mini 5 (A12, iPadOS 26.6.2) in Safari and Edge, which are the same
WebKit as every iPadOS browser, and on Firefox for Windows. The agent's in-app player plays every file below that the
iPad refuses; what each candidate player still cannot is in [[plugins#in-app-player]].

**A playable file needs nothing but Range.** Served as it is by Starlette's `FileResponse`, a file plays, seeks and
resumes: Safari probes `bytes=0-1`, then keeps one open-ended range and opens a new one per seek, which lands in
0.2–0.5 s on a 500 MB file. `timeupdate` fires every 250 ms. A position saved on `pagehide` and `visibilitychange`
survives a reload, a tab switch and a locked screen, and both setting `currentTime` after `loadedmetadata` and a `#t=`
fragment resume to the second. An MP4 whose index sits at the end of the file plays too.

**What the iPad plays as a file:**

| | Plays | Does not |
| --- | --- | --- |
| Container | MP4, MOV, WebM | MKV; MPEG-TS, which Safari plays only as HLS segments |
| Video | H.264 progressive; HEVC tagged `hvc1`, 8- and 10-bit; VP8; VP9 to 4K | HEVC tagged `hev1`; interlaced H.264; AV1 on this chip (A17 Pro and M3 or later decode it) |
| Audio in MP4 | AAC, stereo and 5.1; AC-3 | MP3 and MP2: the picture plays, silent |

Firefox for Windows plays AV1 and MKV and no HEVC, the reverse. **What plays is the client's property, never the
file's.**

**The client says what it decodes.** The watch page asks `navigator.mediaCapabilities.decodingInfo()` with the file's
MIME type and codec string, which the node reads with MediaInfo; on the iPad its answer matched every playback, AV1
included. `canPlayType` without a codec string answers "maybe" to anything in an MP4 and is not used. A file the client
calls unsupported is converted, and so is one that fails with `MEDIA_ERR_SRC_NOT_SUPPORTED` despite the answer.

**Converted on demand, the opened file only.** Nothing is converted in advance or a tutorial at a time: when the watch
page opens a file its client cannot play, the page shows *Preparing this video for this device* with the converter's
progress, then plays the result, a finished MP4 with its index first, served with Range like any other file. No stream
is converted live: HLS, or a transcode restarted at every seek, is not done.

- **Remux** when only the wrapping is wrong: MKV or TS into MP4, `hev1` retagged `hvc1`, MP3, MP2 or broadcast
  AAC-LATM audio re-encoded to AAC with the video copied. It reads the whole file, so its cost is the read: a 1 GB
  tutorial over a gigabit share takes about 10 s.
- **Transcode** when the codec is wrong: AV1, MPEG-2, interlaced H.264 (deinterlaced) into 8-bit H.264 with AAC.

Real time multiples measured on the various machines (higher is faster; below 1 the video plays faster than it
converts):

| Machine | Remux | AV1 1080p 10-bit to H.264 | AV1 4K 10-bit to 1080p H.264 |
| --- | --- | --- | --- |
| PC, Ryzen 5 5600 + RTX 4070 | 41× | 2.4× CPU, 7.5× NVENC | 2.7× CPU, 6.2× NVENC |
| mac mini, M1 | 50× | 2.6× CPU, 3.3× VideoToolbox | 4.1× CPU, 5.9× VideoToolbox |
| mac mini (late 2014), i5-4308U | 20× | 0.63× | 1.1× |
| Fujitsu Esprimo, GX-217GA | 5.6× | 0.13× | 0.21× |
| QNAP TS-230, debian bookworm container, Cortex-A53 | 2.2× | 0.08× | 0.08× |

The remux column copies an H.264 TS and re-encodes its audio; a pure copy ran at 10× even on the TS-230. **A node
transcodes only when it is faster than real time**: the agent's own node on a desktop or laptop transcodes, a small
headless node remuxes and answers that the file needs a stronger machine. Transcoding is one more kind in a node's
permission set ([[nodes#node-status]]).

**The conversion cache.** Converted files live in a folder of the node's own, beside the borrow store and apart from it:
a borrow puts a copy away ([[borrowing]]), the cache adapts a format to a client. An entry is keyed by the original's
path, size and modification time, so an edited original is never served stale; when a new conversion needs room, the
least recently watched entry goes first. A settings page shows the cache's size, clears it and sets its limit (20 GB,
say). Progress is stored against the original file, never the converted one: a remux keeps every timestamp and a
transcode stays within a frame, so a position carries between the agent, the web and back.

**HTTPS, with a certificate the node makes itself.** It must carry the `serverAuth` extended key usage and name the
node's address in its subject alternative names: without `serverAuth`, Safari fails with a TLS error and offers only
*Try again*. With it, Safari shows its warning once per device, and the video element honours the exception the user
accepted: media loaded, seeked and resumed over HTTPS exactly as over HTTP. Plain HTTP played as well and was not
chosen, since one-time passwords and session cookies would cross the LAN in clear
([[discovery-trust-access#user-auth]]).

## §5.9 The web pages: FastAPI, HTMX and Pico

[[[nodes#web-pages]]]

- [#418: spike: a FastAPI + HTMX + Pico follow-mode page](https://github.com/borco/rehuco/issues/418)
- [#440: feat(web): login page and the tutorial list served by a node](https://github.com/borco/rehuco/issues/440)
- [#441: feat(web): watch a tutorial in the browser — resume, progress, viewed](https://github.com/borco/rehuco/issues/441)

The follow-mode spike (#418) built the pages the node needs as a throwaway: a tutorial's file list with per-file
progress, a watch page whose player posts its position every few seconds, and both following a position another
device writes. Driven by script in Edge for Windows and by hand on the iPad in Safari, Edge and Firefox, on FastAPI
0.143 (Starlette 1.8), Jinja2 3.1 and uvicorn 0.54 on Python 3.14, with htmx 2.0.4 and Pico CSS 2.0.6. **The stack
builds the pages as needed**, with a few lines of plain script where a media element or a page leaving is concerned.

**The pages are server-rendered fragments.** Each page is a Jinja2 template; a part that refreshes is a partial the page
includes and an endpoint renders alone, one template for both. A posted value is form-encoded, htmx's default, so the
node depends on `python-multipart` beside `jinja2`. htmx (51 KB) and Pico (82 KB) are served by the node from its own
package, never from a CDN: the machine that travels serves its borrowed tutorials with no internet
([[borrowing#vacation-topology]]).

**Following another device is polling.** The list polls its rows every 3 s and swaps them whole; a position the agent
wrote showed within 3 s. A paused watch page polls every 4 s and, when another device has moved this file's position,
offers *Watched on agent-pc up to 1:10* with a *Jump there* button: it showed 1.8 s after the write. A playing page
does not poll, and never jumps by itself. A device is told apart by an id the browser keeps in `localStorage`.

**The player posts through htmx, the page's exit through a beacon.** htmx listens to media events on the `<video>`
itself: `hx-trigger="every 5s [!this.paused], pause, seeked, ended"` posted every 5 s while playing and once per pause
and seek, and a pause landing while a tick is in flight queues rather than drops, htmx's default. Two traps: a trigger
filter runs with `this` as the element, but a `js:` value in `hx-vals` runs with `this` as `window` and no event, so it
reads the player by id; and the trigger's name reaches the request only through an `htmx:configRequest` listener.
htmx's request is cancelled when the page goes, so `pagehide` and a hidden `visibilitychange` post with
`navigator.sendBeacon` instead, about ten lines of script; both arrived on navigating away. The resume is the
`#t=<position>` fragment ([[nodes#web-playback]]), whose seek posts the resumed position once on load.

**A page writes only a position it moved.** A page left paused at 0:50 while the agent went on to 1:10 would, on
leaving, post 0:50 and send the agent back: the exit beacon and a pause post only when this page played or seeked
since its own last write, and jumping to another device's position is such a seek. The watch page (#441) keeps this
rule.

**Pico needs one rule of the page's own.** The list, its table and `<progress>` bars, the nav, the banner and its
button, and the dark scheme from `prefers-color-scheme` came out right at phone width with no CSS; `<video>` does not
shrink to its container, so the page sets `video { width: 100%; height: auto }`: without it a 1280-pixel video ran off
a portrait window.

**Fullscreen is the page's, where the browser allows it, and a fill everywhere.** A browser's own fullscreen is its
player's, whose X stops the video in Safari, Edge and Firefox on the iPad alike. The page offers two buttons over the
player instead:

- *Full screen* asks the Fullscreen API for a wrapper around the video, never the video itself, and shows only where
  `fullscreenEnabled` says it may. Safari and Edge then hide their tabs and keep the page's *Exit full screen*, which
  leaves without a pause; Firefox hands the video to its own player regardless, so there it ends at the X.
- *Fill page* only adds a class: the wrapper fixed over the whole window on black, `object-fit: contain`. It keeps the
  inline controls and the page's *Exit fill* in all three browsers, follows a rotation, and enters and leaves with no
  pause, but leaves the browser's tabs in place.

Added to the home screen as a web app (a manifest with `display: standalone`), the page opens with no tabs or address
bar, and the Fullscreen API is not offered: *Fill page* is the only button, and fills everything below the status bar,
which stays.

**The iPad cannot be told from a Mac, or simulated.** Its Safari sends a Mac user agent, and Edge a Mac one with
`EdgiOS` in it, so the node never decides by user agent; what a client plays it asks the client
([[nodes#web-playback]]). Playwright's WebKit for Windows plays no video (`MEDIA_ERR_SRC_NOT_SUPPORTED` on the spike's
H.264, though `canPlayType` says *probably*), so a page is checked on the iPad itself.

**One thing later pages decide.** `js:` values and trigger filters are compiled with `Function`, so a content security
policy without `unsafe-eval` needs them moved into a listener.
