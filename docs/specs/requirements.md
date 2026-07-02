# §14. Functional Requirements Carried Into the Architecture

Consolidated list of requirements established across discussion, checked against the design above:

- Browse content across any node from any other node; resources with no live access route show cached info marked offline rather than disappearing (§10.3).
- Request a local copy of a resource for offline use; local copies are marked as copies and tracked as instances (§10.2).
- Duplicate detection across the catalog, with a review UI for ambiguous cases (§10.4, §10.5).
- Per-resource notes, view/watch progress, and bookmarking; ability to delete local viewed files on request.
- Track *why* something was deleted/skipped (via tags/notes), to avoid re-buying or re-downloading it later.
- Admin-managed users and access control: full access, per-resource grants, or dynamic tag-based grants — swarm-propagated, enforced server-side at the serving node (§6.8, §6.10).
- No remote/off-LAN access by design; reach the swarm from outside via a VPN into the home network (§A02.2).
- Checkout → offline use → sync-back of notes/progress, including the implicit-checkout case when storage itself becomes unreachable (§12), and the deliberate borrow/library-shelf case (§11). In v1, offline editing covers per-user state only; resource metadata is online-only-editable (§7).
- Borrows recorded in the user's meta block, supporting multiple simultaneous devices and an explicit return step (§11.4).
- Seamless node handoff during active playback (§9.6).
- Web UI usable from an iPad as a thin client served by a node — a household always-on box at home, or the laptop's node while away (§11.5).
- The Qt app connects to any node on the LAN and always operates as a node client, even on the same machine; editing a node's `.rehuco` browses that node's files (§5.1).
- Tolerating offline mounts without blocking — a node keeps serving when a mounted source box (e.g. the TS-230) is powered off (§9.9).
- Self-mapping of shared storage across nodes via fingerprint files, including detection of double-primary misconfiguration (§9.10, §9.11).
- Node benchmarking/grading to drive task-dispatch decisions quantitatively (§9.12).
- Self-determined fastest/safest move/rename, with checksum-gated cross-filesystem moves (§9.13).
- Extensible resource types via plugins, with tutorial, reference-images, and Daz3D as the initial set (§13).
- Scheduled archival of a borrowed resource's video files on return (fully or selectively, keeping chosen files), preserving metadata/images/extras and tagged as archived (§11.3).
- Durable, configurable local retention of offline-media and remote-node metadata for offline browsing and rebuild survival (§9.8).
