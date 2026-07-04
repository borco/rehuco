# §14. Functional Requirements Carried Into the Architecture

[[[requirements]]]

## Overview

[[[requirements#overview]]]

Consolidated list of requirements established across discussion, checked against the design above:

- Browse content across any node from any other node; resources with no live access route show cached info marked
  offline rather than disappearing ([[instances-and-dedup#failure-model]]).
- Request a local copy of a resource for offline use; local copies are marked as copies and tracked as instances
  ([[instances-and-dedup#instance-registry]]).
- Duplicate detection across the catalog, with a review UI for ambiguous cases ([[instances-and-dedup#deduplication]],
  [[instances-and-dedup#duplicate-review]]).
- Per-resource notes, view/watch progress, and bookmarking; ability to delete local viewed files on request.
- Track *why* something was deleted/skipped (via tags/notes), to avoid re-buying or re-downloading it later.
- Admin-managed users and access control: full access, per-resource grants, or dynamic tag-based grants —
  swarm-propagated, enforced server-side at the serving node ([[discovery-trust-access#user-auth]],
  [[discovery-trust-access#access-control]]).
- No remote/off-LAN access by design; reach the swarm from outside via a VPN into the home network
  ([[appendices.open-questions#still-open]]).
- Checkout → offline use → sync-back of notes/progress, including the implicit-checkout case when storage itself becomes
  unreachable ([[offline-editing#overview]]), and the deliberate borrow/library-shelf case ([[borrowing]]). In v1,
  offline editing
  covers per-user state only; resource metadata is online-only-editable ([[sync#overview]]).
- Borrows recorded in the user's meta block, supporting multiple simultaneous devices and an explicit return step
  ([[borrowing#recording-borrows]]).
- Seamless node handoff during active playback ([[mounts-and-storage#node-handoff]]).
- Web UI usable from an iPad as a thin client served by a node — a household always-on box at home, or the laptop's node
  while away ([[borrowing#vacation-topology]]).
- The Qt app connects to any node on the LAN and always operates as a node client, even on the same machine; editing a
  node's `.rehuco` browses that node's files ([[nodes#two-roles]]).
- Tolerating offline mounts without blocking — a node keeps serving when a mounted source box (e.g. the TS-230) is
  powered off ([[mounts-and-storage#offline-mounts]]).
- Self-mapping of shared storage across nodes via fingerprint files, including detection of double-primary
  misconfiguration ([[mounts-and-storage#fingerprint-map]], [[mounts-and-storage#folder-add]]).
- Node benchmarking/grading to drive task-dispatch decisions quantitatively ([[mounts-and-storage#node-benchmark]]).
- Self-determined fastest/safest move/rename, with checksum-gated cross-filesystem moves
  ([[mounts-and-storage#safe-move-rename]]).
- Extensible resource types via plugins, with tutorial, reference-images, and Daz3D as the initial set
  ([[plugins#overview]]).
- Scheduled archival of a borrowed resource's video files on return (fully or selectively, keeping chosen files),
  preserving metadata/images/extras and tagged as archived ([[borrowing#scheduled-archival]]).
- Durable, configurable local retention of offline-media and remote-node metadata for offline browsing and rebuild
  survival ([[mounts-and-storage#durable-retention]]).
