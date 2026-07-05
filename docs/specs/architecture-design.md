# rehuco — Architecture Design

[[[architecture-design]]]

## Overview

[[[architecture-design#overview]]]

*rehuco — a personal, distributed catalog for tutorials, references, and creative assets.* (The name is the stem of the
file formats it owns: `.rehu`, `.rehuco`, `.rehudb`, `.rehusw`. Successor to TutCatalog, generalized beyond tutorials.)

This file holds the high-level overview ([[architecture-design#problem]]–[[architecture-design#components]]). The rest
of the design lives in topic
files alongside it; see [README.md](README.md) for the **document map** that says which
section number lives in which file, and a suggested reading order.

## §1. Problem Statement

[[[architecture-design#problem]]]

The user has a large, heterogeneous personal media collection spread across multiple machines:

- Local video tutorials (flat or nested folder structures)
- Online tutorials (YouTube and other resources, sometimes mixed with local files)
- Udemy course registrations (large, poorly catalogued, mixed quality)
- Zip archives of reference images, Daz3D plugins, and 3D objects
- Likely more categories over time

Scale: 1–20 users (household), but 5,000–10,000+ tutorials and hundreds to thousands of other resources.

An existing PySide6 app already manages this using a YAML sidecar file (`info.tc`) per tutorial folder, with an SQLite
cache layered on top to solve load-time problems as the catalog grew. The next generation of the system needs to:

- Replace `info.tc` (YAML) with `info.rehu` (JSON) — ~10x faster to parse per the user's benchmarks
- Scale across multiple physical machines, not just one
- Support offline/disconnected use (laptop, USB stick, optical media)
- Support multi-user access control at household scale
- Support a web interface for low-power hardware (QNAP) and tablet access
- Support extensible resource types via a plugin model

## §2. Why a Distributed, Self-Describing Design

[[[architecture-design#why-distributed]]]

Two properties drive most of the architecture:

1. **Self-describing data.** `.rehu` files live next to the content they describe. A resource can be copied, moved to a
   different disk, moved to a different node, backed up, checked out, or read from completely offline media (USB stick,
   CD/DVD) — and it still carries everything needed to reconstruct its catalog entry. The cached database (SQLite or
   similar) is rebuildable from scratch by rescanning `.rehu` files; it is a cache, never the source of truth.

   **Precise rebuildability boundary** (refined from earlier discussion): not *all* state is rebuildable purely by
   scanning files reachable at rebuild time. Two categories need care:

   - **Retained metadata copies** of usually-offline sources (external drives, USB sticks, CD/DVD) and optionally of
     other nodes, kept locally per `.rehuco` opt-in ([[mounts-and-storage#durable-retention]]). These *are*
     rebuildable-by-rescan, because they're stored as local files a scan will find — that's the whole point of retaining
     them, so an offline DVD's catalog entry doesn't vanish during a rebuild just because the disc is on a shelf.
   - **The instance registry's knowledge of transient instances** (e.g. an active checkout on a laptop currently
     elsewhere) is *not* reconstructable by scanning local files — nothing local records that a copy is out in the
     world. These are allowed to be forgotten on a full rebuild and to re-register themselves when they next
     reconnect/sync ([[instances-and-dedup#instance-registry]]). Borrows are a partial exception: because a borrow is
     recorded in the user's meta block inside the resource's own `.rehu` ([[borrowing#recording-borrows]]), it survives
     rebuild wherever that `.rehu` is itself retained or reachable.

   The practical implication: full rebuild-from-scratch is still supported, but it is no longer entirely "free" — it
   forgets transient, non-retained instances. The old habit of frequent full rebuilds (driven historically by the
   absence of schema migrations and by stale-data anxiety) should be retired in favor of schema migrations plus cheap,
   version-aware incremental reconciliation ([[data-model#scan-and-staleness]]), with full rebuild demoted to a rare
   recovery tool.

2. **No single always-on machine.** The user's hardware is heterogeneous (Windows 11 PC, Debian Linux PC, Mac mini M1,
   QNAP TS-230 NAS) and not all of it is equally reliable or powerful. Rather than design around one central server, the
   system is built as a **swarm of peer nodes**, each capable of answering for itself, and each tolerant of any other
   node — or any other *resource's storage* — being unreachable.

This pushes the design toward a **distributed system with eventual consistency**, not a client-server app with a single
backend. That's a deliberate, scope-increasing choice — worth stating plainly, since it affects build order and where
complexity lives.

## §3. Components

[[[architecture-design#components]]]

**Core principle — the agent (desktop GUI) is a node client for swarm operations; "admin" is a logged-in user's
privilege, not a separate app ([[nodes#two-roles]]).** The desktop GUI talks to a node rather than touching the catalog
filesystem itself, removing "local path vs. remote node" special-casing. The bare single-file viewer is the one
exception — it opens a local `.rehu` off disk with no node and no login ([[nodes#local-vs-swarm]]).

| Component | Role |
| --- | --- |
| **Agent** (PySide6 desktop GUI) | Tray icon, viewer/editor, catalog/admin UI. A node client ([[nodes#two-roles]]). Exposes admin functions only when an admin *user* is logged in ([[discovery-trust-access#user-auth]]) — there is no separate "admin build". Runs only on machines with a display. |
| **Local viewer/editor** (part of the agent) | Views/edits a single `.rehu` file. Registered as the default `.rehu` handler in File Explorer (double-click opens it, [[nodes#single-instance]]). Works in local-file mode with no node/login ([[nodes#local-vs-swarm]]). Behavior is supplied by the resource's **plugin** ([[plugins#overview]]). |
| **Node** | Headless service: watches folder roots, serves `.rehu` data over REST, participates in the swarm, runs jobs. Runs on every machine including headless ones (QNAP). No GUI. Multiple per machine (different config/data dirs, ports). Per root, **primary/local** (owns files, authoritative writer) or **remote/mounted** (serves a mount it doesn't own) — chosen at folder-add ([[mounts-and-storage#folder-add]]). Independent lifecycle from the agent ([[nodes#two-roles]]). |
| **Task queue / dock** | Visible, app-wide queue of slow operations (checksum, sync, scans, copies, node-notify, benchmarking, safe moves). Pause/resume/cancel/reorder. Multi-selecting serializes work rather than running it all at once. All background swarm chatter lives here, surfaced as status not a blocking gate ([[nodes#readiness-per-op]]). |
| **Web interface** | Served by a node for browser access — primarily the iPad/tablet, a pure thin client ([[borrowing#vacation-topology]]) that only views what a reachable node serves over HTTPS and never holds offline state. At home: a household always-on node; away: the laptop's node over LAN/hotspot. Rendering supplied by the resource's plugin. |
| **Plugins** | Define resource types (tutorial, reference images, Daz3D, future). Own schema extensions, viewer/editor UI, web rendering, and custom actions ([[plugins#overview]]). |
