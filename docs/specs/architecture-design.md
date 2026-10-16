# rehuco — Architecture Design

[[[architecture-design]]]

## Overview

[[[architecture-design#overview]]]

*rehuco — a personal catalog for tutorials, references, and creative assets, shared from one place.* (The name is the
stem of the file formats it owns: `.rehu`, `.rehuco`, `.rehudb`, `.rehuser`. Successor to TutCatalog, generalized
beyond tutorials.)

This file holds the high-level overview ([[architecture-design#problem]]–[[architecture-design#components]]). The rest
of the design lives in topic files alongside it; see [README.md](README.md) for the **document map** that says which
section number lives in which file, and a suggested reading order.

> [!NOTE]
> **The design turned on 2026-10-16** (#509). Until then it described a *swarm*: every root owned by a node that was
> its sole writer, with a sync engine, an instance registry and pairing between nodes. That is gone
> ([[appendices.post-mortem#architecture]]). The files live on an SMB share and the operating system's mount is the
> transport; what follows is designed to hold with **no node present at all**, because anyone may mount the share
> directly. The node is an auxiliary the agent runs beside itself.

## §1. Problem Statement

[[[architecture-design#problem]]]

The user has a large, heterogeneous personal media collection, kept on a NAS and reached from several machines:

- Local video tutorials (flat or nested folder structures)
- Online tutorials (YouTube and other resources, sometimes mixed with local files)
- Udemy course registrations (large, poorly catalogued, mixed quality)
- Zip archives of reference images, Daz3D plugins, and 3D objects
- Likely more categories over time

Scale: 1–20 users (household), but 5,000–10,000+ tutorials and hundreds to thousands of other resources.

An existing PySide6 app already manages this using a YAML sidecar file (`info.tc`) per tutorial folder, with an SQLite
cache layered on top to solve load-time problems as the catalog grew. The next generation of the system needs to:

- Replace `info.tc` (YAML) with `info.rehu` (JSON) — ~10x faster to parse per the user's benchmarks
- Work from several machines at once, Windows, macOS and Linux, on the same files over the share
- Support offline/disconnected use (a machine that travels, USB stick, optical media)
- Keep each household user's own state apart from the others' and from the shared details
- Support a web interface for a tablet
- Support extensible resource types via a plugin model

## §2. Why Self-Describing Data, and Why the Share Is Enough

[[[architecture-design#why-distributed]]]

Two properties drive most of the architecture:

1. **Self-describing data.** `.rehu` files live next to the content they describe. A resource can be copied, moved to a
   different disk, borrowed onto another machine, backed up, or read from completely offline media (USB stick, CD/DVD)
   — and it still carries everything needed to reconstruct its catalog entry. The cached database (`.rehudb`) is
   rebuildable from scratch by rescanning `.rehu` files; it is a cache, never the source of truth.

   **Precise rebuildability boundary:** not *all* state is rebuildable purely by scanning files reachable at rebuild
   time. Two categories need care:

   - **Retained metadata copies** of usually-offline sources (external drives, USB sticks, CD/DVD), kept locally per
     root opt-in ([[mounts-and-storage#durable-retention]]). These *are* rebuildable-by-rescan, because they're stored
     as local files a scan will find — that's the whole point of retaining them, so an offline DVD's catalog entry
     doesn't vanish during a rebuild just because the disc is on a shelf.
   - **Borrowed copies** on other machines. A borrow is recorded beside the copy itself, in a `.borrow` file in the
     node's borrow store ([[borrowing#recording-borrows]]), so it survives wherever that copy does; a machine that is
     away is known from the last answer its node gave. Nothing at the origin records a borrow.

   The practical implication: full rebuild-from-scratch is supported and cheap, and the old habit of frequent full
   rebuilds (driven historically by the absence of schema migrations and by stale-data anxiety) is retired in favor of
   schema migrations, a file notifier ([[mounts-and-storage#out-of-band]]) and cheap, version-aware incremental
   reconciliation ([[data-model#scan-and-staleness]]), with full rebuild demoted to a rare recovery tool.

2. **The share is the system of record; the mount is the transport.** The user's hardware is heterogeneous (Windows 11
   PC, Debian Linux PC, Mac mini M1, QNAP TS-230 NAS) and not all of it is equally reliable or powerful. The files sit
   on the NAS, served over SMB ([[packaging-deployment#ts230-as-nas]]), and every machine reaches them through its own
   mount — reading, writing, copying and watching them with what the operating system and the SMB server already
   provide. Nothing of rehuco's stands between a machine and the files, so nothing of rehuco's has to be running for
   the files to be reachable, and two machines editing the same record are kept apart by the share itself
   ([[sync#overview]]), not by a server rehuco runs.

This pushes the design toward a **local-first application over a shared filesystem**, not a distributed system: the
hard problems a swarm of peers would have had — who owns a file, how edits made apart converge, how a node learns a
file changed — are answered by the filesystem (an exclusive-create lock and an atomic replace), by comparing content
before writing, and by the server's change notifications. The one piece that is more than a desktop app, the **node**,
serves what a filesystem cannot: web pages for a tablet, long jobs, a store for borrowed copies ([[nodes]]).

## §3. Components

[[[architecture-design#components]]]

**Core principle — the agent and the node are thin hosts over rehuco-core; "admin" is a logged-in web user's
privilege, not a separate app ([[nodes#two-roles]]).** Both read and write the files through the same Qt-free core
classes ([[nodes#access-seam]]), and neither has rights the other lacks: a node is one more client of the share. The
bare single-file viewer needs no node and no login ([[nodes#local-vs-swarm]]).

| Component | Role |
| --- | --- |
| **Agent** (PySide6 desktop GUI) | Tray icon, viewer/editor, the catalog with its roots and browsers, the settings. Local-first: every root is a folder this machine can reach, local or mounted ([[mounts-and-storage#rehuco-scope]]). Hosts this machine's node as a child process while it runs ([[nodes#two-roles]]). Runs only on machines with a display. |
| **Local viewer/editor** (part of the agent) | Views/edits a single `.rehu` file. Registered as the default `.rehu` handler (double-click opens it, [[nodes#single-instance]]). Works with no node and no catalog open ([[nodes#local-vs-swarm]]). Behavior is supplied by the resource's **plugin** ([[plugins#overview]]). |
| **Node** | A process the agent starts beside itself and stops when it quits, running as the agent's user on every OS. It owns no roots: it serves the user's roots that its machine reaches, plus its **borrow store**. Today it keeps a heartbeat and a log; it is where the web pages for a tablet, the long jobs and borrowing land ([[nodes#overview]]). |
| **File notifier** | One change source for everything the app shows: native filesystem events for local disks, the SMB server's own change notifications for shares, polling as the floor ([[mounts-and-storage#out-of-band]]). Every view listens to it; nothing announces its own writes to the others. |
| **Task queue / dock** | Visible, app-wide queue of slow operations: checksums, scans, copies, and **every save** — a save is a job that takes the record's lock, compares the file with what the edit was based on, merges and writes ([[sync#overview]]). Pause/resume/cancel/reorder; written down so it survives quitting, which is what makes a save made offline wait for the share to come back. The engine and the decisions behind it are [[appendices.task-queue]]. |
| **Web interface** | Served by the node for browser access — primarily the iPad/tablet, a pure thin client ([[borrowing#vacation-topology]]) that only views what a reachable node serves and never holds offline state. At home: the node of a machine that is on; away: the node of the machine that travels. Rendering supplied by the resource's plugin. |
| **Plugins** | Define resource types (tutorial, reference images, Daz3D, future). Own schema extensions, viewer/editor UI, web rendering, and custom actions ([[plugins#overview]]). |
