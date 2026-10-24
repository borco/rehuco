# §14. Functional Requirements Carried Into the Architecture

[[[requirements]]]

## Overview

[[[requirements#overview]]]

Consolidated list of requirements established across discussion, checked against the design above:

- Browse the catalog on any machine that mounts the share; a root whose share is offline shows its cached rows marked
  offline rather than disappearing ([[mounts-and-storage#offline-mounts]], [[instances-and-dedup#failure-model]]).
- Edit the same records from several machines at once, and beside anyone who mounts the share without rehuco, with no
  silent overwrite: a save takes the record's lock, compares the file with what the edit was based on, and shows a
  conflict rather than losing an edit ([[sync#overview]]).
- Every machine learns of a change made by another within about a second on a share that notifies, and within one
  polling period everywhere else, without a scan ([[mounts-and-storage#out-of-band]]).
- Per-resource notes, view/watch progress, and bookmarking; ability to delete local viewed files on request. Progress
  is per video file — a resume position and a *viewed* flag, totalled per folder — recorded by the agent and the web
  UI and carried between them ([[field-schema#watch-progress]]). Each user's state lives in that user's own sidecar
  beside the record ([[data-model#single-file]]).
- Track *why* something was deleted/skipped (via tags/notes), to avoid re-buying or re-downloading it later.
- Users of the web pages log in with a one-time password issued for their name by the node's CLI, with an admin role
  that sees every user's jobs and borrows ([[discovery-trust-access#user-auth]]).
- No remote/off-LAN access by design; reach home from outside via a VPN ([[appendices.open-questions#still-open]]).
- Offline use: per-user edits made while the share is unreachable wait as persisted jobs and land when it is back
  ([[offline-editing#overview]]); details are editable only while the file is reachable ([[sync#overview]]).
- Borrow a resource onto a machine by a verified, resumable copy into that machine's node's borrow store, one copy per
  resource per box however many users borrow it; return it by each user, or for all by an admin; the copy goes when the
  last borrower returns ([[borrowing]]). A second borrow of the same resource is refused by its UUID against every
  reachable node's records ([[borrowing#recording-borrows]]).
- Web UI usable from an iPad as a thin client served by a node — a machine that is on at home, or the machine that
  travels while away ([[borrowing#vacation-topology]]).
- The same `.rehuco` opens on every machine: each root has a machine-independent location, and each machine keeps its
  own mapping of it, resolved from the mount table or asked for once; an unmapped root is visible but disabled
  ([[mounts-and-storage#rehuco-scope]]).
- Tolerating offline mounts without blocking — the agent keeps working, and the node keeps serving what it reaches,
  when a mounted source box (e.g. the TS-230) is powered off ([[mounts-and-storage#offline-mounts]]).
- Self-determined fastest/safest move/rename, with checksum-gated cross-filesystem moves
  ([[mounts-and-storage#safe-move-rename]]).
- Long operations — checksum runs, verified copies — run as jobs, and may run on a node whose disk holds the files, as
  an optimisation ([[nodes#node-status]]).
- Extensible resource types via plugins, with tutorial, reference-images, and Daz3D as the initial set
  ([[plugins#overview]]).
- Scheduled archival of a borrowed resource's video files on return (fully or selectively, keeping chosen files),
  preserving metadata/images/extras and tagged as archived ([[borrowing#scheduled-archival]]).
- Durable, configurable local retention of offline-media metadata for offline browsing and rebuild survival — per root,
  forced for removable roots and on by default for network ones ([[mounts-and-storage#durable-retention]]).
- Duplicate detection across the catalog, with a review UI for ambiguous cases ([[instances-and-dedup#deduplication]],
  [[instances-and-dedup#duplicate-review]]).
