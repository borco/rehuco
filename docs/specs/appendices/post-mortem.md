# Post-Mortem — Abandoned and Replaced Approaches

[[[appendices.post-mortem]]]

A short catalog of approaches that were tried, prototyped, or seriously considered and then **abandoned or
replaced** — kept so they are neither silently re-attempted nor forgotten. Each entry names the approach, why
it was dropped, and where the current design lives. Where a decision has a fuller account in another doc, that
doc is the detailed home and the entry here is a one-line pointer.

> [!NOTE]
> This is deliberately terse, and records *dead ends* — not the current design. For what the project does now,
> follow the pointer to the owning doc.

## Documentation and tooling

[[[appendices.post-mortem#docs-tooling]]]

- **Bare `§N.M` cross-references.** The specs first referenced each other by global section number. Inserting a
  *document* shifted every later number and every reference to it, project-wide; whole-chapter references had
  nowhere stable to point. Replaced by the grep-based `[[doc#slug]]` token scheme. Detail, and the rejected
  syntax candidates that preceded `#`: [[readme#why-not-numbers]].
- **`mkdocs-kroki-plugin` for diagrams.** An early diagram-rendering choice, dropped for its heavier dependency
  chain; replaced by `mkdocs-puml` rendering `plantuml` fences against a PlantUML server (self-hosted in CI).
  Detail: [diagrams/README.md](../diagrams/README.md).

## UI, docking, and deployment

[[[appendices.post-mortem#ui-and-deployment]]]

- **KDDockWidgets for the dock manager.** More capable as a framework, but GPL — linking it would make the whole
  agent a GPL combined work — and it ships no PyPI wheel. Foreclosed; the app uses `pyqtads` (LGPL, prebuilt
  PySide6 bindings), with QML surfaces hosted in `QQuickWidget` docks. Detail:
  [[packaging-deployment#licensing-policy]].
- **Running the node directly on the QNAP TS-230.** The TS-230 was considered as a compute host for
  `rehuco-node`; abandoned — it is treated purely as NAS storage (an SMB share), and the node runs on capable
  hardware that mounts it. Detail: [[packaging-deployment#ts230-as-nas]]. The glibc-compatibility canary run for
  that abandoned path is kept as reference in [[packaging-deployment#glibc-canary]].
- **Per-site HTML scrapers (geckodriver + BeautifulSoup).** The predecessor projects' acquisition approach:
  brittle, per-site, and repeatedly broken by site changes. Abandoned as *shipped code the release owns*, and revived
  as user-overridable scraper Protocols loaded from a scripts folder ([[acquisition-tooling#scraper-registry]]) — the
  brittleness is real and now belongs to a `.py` the user edits, with LLM-assisted extraction kept as the fallback for
  hosts no script matches rather than as the replacement. An earlier draft had it the other way round: LLM-assisted
  URL extraction as the successor, per-site code never to return. Detail: [[acquisition-tooling#url-extract]] (and the
  predecessor
  [histories](../history/README.md) that carried it).

## Architecture

[[[appendices.post-mortem#architecture]]]

- **The swarm** (dropped 2026-10-16, #509). Every root owned by one node that was its sole writer; a sync engine with
  version vectors, an append-only activity log, tombstones and a verdict queue; an instance registry; a swarm ID,
  pairing by device ID with mutual TLS, a hub-and-spoke membership pushed to every node; a propagated `.rehusw` with
  users and hashes; serve-after-resync; fingerprint files and a primary/remote flag per root; a change journal over
  SSE; and a `ResourceAccess` seam with a `NodeKey` so the agent could reach a node's roots as if local (#413–#417,
  #420–#453). Dropped because the files were already on an SMB share: the operating system's mount and the SMB
  server's own primitives — an atomic exclusive create for the lock, an atomic rename for the write, `CHANGE_NOTIFY`
  for changes — answer every question the swarm answered, and hold with no node present, which the swarm never could.
  The node became an auxiliary the agent runs beside itself. Detail: [[architecture-design#why-distributed]],
  [[sync#overview]], [[mounts-and-storage#out-of-band]].
- **The agent as a node client for every swarm operation.** The agent was to reach the catalog only through a node,
  never reading it from the filesystem itself. Replaced first by #409's local-first agent, then by the end of node
  ownership altogether (above). Detail: [[nodes#local-vs-swarm]].
- **A node never embedded in the agent** (#405), then **a node as an installed system service** (#504). The service
  was measured on Windows: it sees none of the users' mounts and credentials, cannot run from a per-user install, and
  must be granted its way into profile folders, at the price of UAC prompts the owner would not inflict on users.
  Replaced by the node as the agent's child, running as the agent's user, serving only while that user is logged in;
  the service recipe is kept on #504 as a possible later opt-in. Detail: [[nodes#two-roles]].
- **OS byte-range locks for the record** (#503). `fcntl`/`flock` over SMB differ per client (macOS ignores them,
  Linux maps them to SMB locks only since 5.5, Windows locks are mandatory); an exclusive-create lock file is the one
  primitive all three honour. A lock *held open* was also abandoned after the macOS client's deferred close kept a
  deleted lock alive for a minute. Detail: [[sync#lock-file]].
- **A per-user sidecar rejected for splitting the record** ([[data-model#single-file]]'s earlier text). Reversed once
  per-user writes every few seconds, from several machines, were going into one shared record.
- **rsync for borrows and moves.** The Python wrappers are tiny and unmaintained, and delta transfer buys nothing for
  immutable content; what rsync would have given is resumption, which the verified copy does itself. Detail:
  [[mounts-and-storage#safe-move-rename]].
- **No disk watcher, by policy** ([[mounts-and-storage#out-of-band]]'s earlier text: "an unwanted resource cost").
  Reversed: a notifier over the SMB server's own change notifications costs the client nothing and is what lets every
  machine follow the others without scans.

## Process

[[[appendices.post-mortem#process]]]

- **Building layers deeply in isolation before a working whole.** Earlier attempts (notably TutCatalog5) built a
  full field/type system before anything worked end-to-end, and never reached a usable product. Replaced by
  **tracer-bullet-first** slices — a thin, kept, end-to-end spine per milestone, thickened afterward. Detail:
  [[implementation-plan#methodology]].
