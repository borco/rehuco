# Open Questions — Out of Scope and Not Yet Designed

[[[appendices.open-questions]]]

## Overview

[[[appendices.open-questions#overview]]]

Flagging gaps so they're a deliberate choice rather than an oversight.

## 1. Resolved or scoped since the first consolidation

[[[appendices.open-questions#resolved-or-scoped]]]

- **Metadata-conflict during offline editing** — previously an unacknowledged contradiction between [[sync#overview]]
  ("single writer, no conflict") and [[offline-editing#overview]] ("cache stays editable offline"). Resolved for v1 by
  making resource metadata online-only-editable ([[sync#overview]]); only per-user state is offline-editable. The hard
  multi-writer-metadata merge is a future hook, not v1 work.
- **Instance-registry / offline-instance persistence** — the rebuild-from-scratch model was imprecise. Now bounded
  ([[architecture-design#why-distributed]]): retained metadata copies ([[mounts-and-storage#durable-retention]]) survive
  rebuild by rescan; transient instances re-register on reconnect; borrows persist via the user meta block
  ([[borrowing#recording-borrows]]).
- **Per-image metadata location** — clarified ([[data-model#image-meanings]]): app-managed mutable metadata alongside
  `.rehu`, never inside the immutable checksummed zip.
- **Scanning strategy** — incremental, version-aware reconciliation is now the normal mode; full rescan demoted to
  recovery ([[data-model#scan-and-staleness]]).
- **Node identity scheme** — replaced the pairing-secret design with Syncthing-style cert-hash device IDs
  ([[discovery-trust-access#node-identity-pairing]]), where identity *is* the key and the introducer model
  ([[discovery-trust-access#membership-model]]) matches the existing hub-and-spoke choice.
- **App/filesystem coupling** — resolved by making the Qt app always a node client ([[nodes#two-roles]]), removing the
  local-vs-remote dual code path.
- **Cross-node storage topology** — was reactive per-resource UUID matching only; now also proactive via fingerprint
  self-mapping ([[mounts-and-storage#fingerprint-map]]), which additionally guards the single-primary rule
  ([[mounts-and-storage#folder-add]]).
- **Deletion / tombstone propagation** — resolved ([[sync#overview]]): deletion is an ordinary logged action whose
  tombstone is its position in the version vector, so offline nodes apply it on reconnect and rescans don't resurrect.
  Delete-vs-concurrent-edit surfaces in the verdict queue ([[instances-and-dedup#duplicate-review]]) rather than
  silently applying. Borrow-vs-delete/archive has an explicit resolution ([[borrowing#borrow-vs-delete]]).
- **Clock skew / ordering** — resolved ([[sync#overview]]): ordering is by per-node-counter version vector,
  clock-independent; wall-clock timestamps are no longer load-bearing. History is the `versions` list — indexed, dated,
  hashed, commented entries; append-only, shrinkable only by logged compaction ([[sync#overview]]).
- **Per-user authentication** — resolved ([[discovery-trust-access#user-auth]]): salted Argon2id hashes propagated to
  every node (since any node can serve a login), passwords never stored/transmitted; thin tablet logs in via session
  against its serving node.
- **Visitors / cross-swarm sharing** — resolved ([[discovery-trust-access#cross-swarm-sharing]]): visitors never join as
  nodes (guest account or stripped export/import instead); no cross-swarm federation.
- **Access control model** — resolved ([[discovery-trust-access#access-control]]): rules are swarm-wide propagated
  config (not per-machine `.rehuco`), enforced server-side at the serving node, with tag-grants evaluated dynamically.
  Remaining work is the concrete rule grammar/schema, not the model.
- **Local file layout** — resolved ([[data-model#local-file-trio]]): `.rehuco` (per-machine config), `.rehudb`
  (disposable cache), `.rehusw` (durable, propagated swarm info).
- **Startup consistency for access rules** — resolved ([[discovery-trust-access#serve-after-resync]]):
  serve-after-resync, stated as "catch up to the most-current reachable source, else serve last-known," with a `.rehusw`
  version marker making "more current" decidable. Resync source resolved by [[discovery-trust-access#registry-home]].
- **Registry home** — resolved ([[discovery-trust-access#registry-home]]): preferred authority (always-on box) when
  reachable, else chatter for highest version, else last-known; single node is the degenerate case. Single-writer admin
  config + version markers means no consensus protocol needed.
- **Single-node / bootstrap operation** — resolved ([[multiplicity#single-node-base]]): the lone node is the base case —
  its own registry authority, serves immediately without waiting for peers; create-swarm and single-node-forever are the
  same path.
- **Node vs. agent split** — resolved ([[nodes#two-roles]]): node = headless service (runs everywhere incl. QNAP); agent
  = desktop GUI (tray + viewer/editor + catalog), a node client, GUI machines only. Independent lifecycles; quitting the
  agent leaves the node serving. "Admin" is a logged-in user's privilege, not a separate build.
- **App readiness / responsiveness** — resolved ([[nodes#readiness-per-op]]): per-operation readiness, not one global
  gate; local-file and cached operations never block on swarm sync; all swarm chatter is async background (task queue)
  surfaced as status.
- **Local-file vs. swarm mode / no-node viewing** — resolved ([[nodes#local-vs-swarm]]): the single-file viewer needs no
  node or login (viewing a local file isn't access-controlled); swarm mode enriches when a node/session is present.
- **Single-instance & file association** — resolved ([[nodes#single-instance]]): bind-or-forward single-instance, one
  main agent hosts both scopes, forwarded opens never block on login, stale-socket reclaim, socket scoped
  per-user-and-swarm.
- **Login persistence** — resolved ([[discovery-trust-access#user-auth]]): agent caches a session token (not the
  password) in the OS secure store; revocation reaches the agent when the token fails.
- **`.rehu` write integrity** — resolved ([[data-model#write-integrity]]): universal atomic temp-then-rename; managed
  files route through the owning node whenever a route exists (single writer), with routeless direct writes tolerated as
  out-of-band changes reintegrated via notification / verify-on-access / scan ([[mounts-and-storage#out-of-band]],
  [[data-model#scan-and-staleness]]); unmanaged files written directly by the agent; import is the explicit
  unmanaged→managed hand-off.
- **`.rehu` schema format versioning** — resolved ([[data-model#schema-version]]): per-file format-version field; newer
  reader upgrades older files, older reader preserves unknown fields rather than dropping them; import is an upgrade
  point.
- **Plugin block model** — resolved ([[plugins#plugin-blocks]]/[[plugins#fallback-editor]]): plugin fields in separate
  keyed, independently-versioned blocks; exactly one live block per `type` (installed-ness doesn't promote inert
  blocks); save-persistence invariant (live type, or never-claimed foreign payload) with claim-then-abandon dropping on
  save; generic fallback editor with carry/map/drop and provenance-aware flagging; discards logged.
- **Plugin spectrum (declarative ↔ code)** — resolved ([[plugins#core-vs-plugin]]): simple types are declarative
  field-lists over a shared field toolkit (no code, no trust surface); rich types are code plugins using the same
  toolkit plus custom widgets/actions. Unifies the code-plugin and TutCatalog5 `.rehuco`-declared-fields ideas.
- **Resource browsers** — resolved ([[plugins#browsers]]): generic browser (common columns) + per-type browsers
  (plugin-contributed columns + cover rendering), table/shelf modes, click-to-filter on tag/author/publisher restored
  from TutCatalog4.
- **Acquisition & migration tooling** — specced ([[acquisition-tooling#overview]]): three drag-drop aids (HTML→Markdown,
  image→screenshot, URL→extract), local-LLM extraction with constrained decoding, `.tc`→`.rehu` migration as format-v0.
  Deferred until after the tutorial web viewer.
- **Code organization, packaging & deployment** — resolved ([[packaging-deployment#overview]]): monorepo with uv
  workspaces (single `.venv` fixes the venv-confusion and makes cross-package refactors atomic); three published
  packages (`rehuco-core`, `rehuco-node`, `rehuco-agent`) mapping onto the shared-lib/node/agent split;
  `uv tool install` for node and agent; the TS-230 serves as a NAS over SMB while the node runs on capable hardware
  ([[packaging-deployment#ts230-as-nas]]), so the glibc constraint is moot (canary findings kept in
  [[packaging-deployment#glibc-canary]] for reference); platform markers keep GUI deps out of the node.
- **Offline revocation limitation** — acknowledged as a deliberate accepted boundary
  ([[discovery-trust-access#serve-after-resync]]): revocation can't reach an already-held local copy that never
  reconnects; trusting household members who kept a copy is an explicit non-goal. Revocation does apply on reconnect.
- **Desktop distribution, file association & app identity** — analyzed
  ([[packaging-deployment#app-identity]]/[[packaging-deployment#auto-update]]): the agent is dual-channel (`uv tool` for
  the author's own machines/devs; a native installer for wider reach); file association is OS-specific with macOS as the
  binding constraint; Windows taskbar identity is an identity-registration matter, not a reason to freeze the app;
  **Briefcase** is chosen for end-user installers over PyInstaller, with MSIX a possible later upgrade; auto-update
  checks a public version oracle and delegates installation to the platform installer. All wider-distribution polish,
  off the personal critical path.
- **File-association + app-identity mechanics** — now **proven on current versions** by the Pre-work spikes: macOS (#13)
  — a Briefcase `.app` registers the extension (UTI + `CFBundleDocumentTypes`) and double-clicks arrive as
  `QFileOpenEvent` into the single instance ([[nodes#single-instance]]); Windows (#1) — an HKCU ProgID default handler
  plus an in-process launcher's AUMID give double-click-open and correct taskbar pin/running. The Briefcase how-to and
  per-OS hurdles are captured in [[appendices.briefcase-packaging#overview]] (and
  [[appendices.windows-dev-launcher#overview]] for the Windows dev launcher). Only code-signing/notarization remains
  open below.

## 2. Still open

[[[appendices.open-questions#still-open]]]

- **Full `.rehu` schema** — field ownership (common vs. plugin) is settled ([[data-model#rehu-format]],
  [[plugins#core-vs-plugin]]); the complete field list/types per plugin is being designed separately. Archival is a tag
  ([[borrowing#scheduled-archival]]), not a schema state. The schema must now also carry the version vector and the
  `versions` history list ([[sync#overview]]) and the user/auth records ([[discovery-trust-access#user-auth]]).
- **Access-rule grammar/schema** — the *model* is settled ([[discovery-trust-access#access-control]]: swarm-propagated,
  server-enforced, full/per-resource/dynamic-tag grants). What's not yet specified is the concrete representation: how a
  grant is written, how per-resource and tag-grants combine (additive? can a deny override an allow?), and where exactly
  it sits in the propagated registry.
- **Session-token portability across nodes** — the user list propagates so any node can verify a *login*
  ([[discovery-trust-access#user-auth]]), but the session token the agent caches is issued by one serving node, while
  the agent is expected to connect to any node ([[requirements#overview]]) and playback hands off between nodes
  ([[mounts-and-storage#node-handoff]]). Per-node sessions (re-login on switch) vs. a swarm-shared token-signing key
  propagated in `.rehusw` — not decided.
- **Remote (off-LAN) access** — *deliberately out of scope, not a gap.* The whole trust/discovery model
  ([[discovery-trust-access]]) is
  LAN-local by design. The app provides no remote-access mechanism and will not put a personal media catalog on the
  public internet. A user who needs access from outside, without standing up their own mobile node, should **VPN into
  the home network** (WireGuard/Tailscale/etc.) — at which point they are "on the LAN" and everything works unchanged.
  This cleanly delegates remote-access security to mature purpose-built software instead of reinventing it in the app;
  the app stays simple and LAN-trusting, the VPN decides who may reach the network at all.
- **Tablet video playback and browser TLS trust** — [[borrowing#vacation-topology]] assumes the iPad plays what a node
  serves over HTTPS, but iOS Safari natively plays only H.264/HEVC in MP4/MOV containers (tutorial catalogs are
  MKV-heavy) and rejects self-signed certificates unless a profile/CA is installed and trusted per device; video serving
  also needs HTTP Range support for seeking. Lossless remux (`ffmpeg -c copy` where the codec is already H.264),
  transcode, HLS, or plain HTTP on the trusted LAN — undecided; slated as a pre-B spike (implementation plan).
- **Instance-registry replication detail** — the *home* is resolved ([[discovery-trust-access#registry-home]]: it lives
  with the preferred authority / propagates like the rest of the registry). What's not yet detailed is the concrete
  shape of the instance registry's own propagation and how transient instances (active checkouts) register/expire within
  it — the location question is settled, the replication mechanics aren't fully drawn.
- **One primary instance per UUID** — [[mounts-and-storage#folder-add]]'s exactly-one-primary rule is per *storage* and
  fingerprint-guarded ([[mounts-and-storage#fingerprint-map]]); it cannot see two same-UUID *copies* on different
  storage both sitting under primary roots (e.g. a backup HDD attached and added as a primary/local root). Needs an
  instance-registry-level invariant ([[instances-and-dedup#instance-registry]]): a UUID scanned under a primary root
  that already has a live primary elsewhere is flagged for a role decision (default `backup`), never silently
  double-primary.
- **Export/import mechanics** — the rules are decided (keep UUID, scrub vector/log/per-user-state/instance entries,
  [[discovery-trust-access#cross-swarm-sharing]]); the concrete on-disk export format and the import-side UUID-collision
  handling aren't designed.
- **Block-level transfer for re-copies** — noted (Syncthing's chunk-hash-and-transfer-only-diffs approach) as worth
  borrowing *narrowly* for refreshing a backup/move where a prior version exists at the destination; no help for
  first-time copies. Not designed; lower priority.
- **Admin identity permanence** — flagged in [[discovery-trust-access#admin-portability]], not resolved (distinct from
  registry home, which is decided).
- **Online-only and mixed local/online resources** — needs schema representation; not detailed.
- **Udemy integration** — registered courses are hard to track; no scraping/API/import approach discussed.
- **3D objects as a resource category** — mentioned alongside Daz3D but not mapped to a plugin design.
- **Shared timed-presentation capability** — identified as worth extracting ([[plugins#shared-capability]]) but not
  designed.
- **Drawing comparison/critique pipeline** — exploratory ([[plugins#refimages-plugin]]); needs prototyping before being
  committed.
- **Where a type's field-list/schema is declared** — the field toolkit ([[plugins#field-toolkit]]) is settled, but
  *where
  the ordered field list for a type is authored* is not. `.rehuco` already declares which plugins load
per machine ([[mounts-and-storage#rehuco-scope]]) but says nothing about field lists. The original tc5/resource-hub idea
was to
  declare field lists **in `.rehuco` itself**, so different `.rehuco` files (spanning different root
  folders) could define different field sets for the same type — one machine/root's "Tutorial" need not
  match another's. For A2.0 the field list is simply a **hardcoded Python constant**, parsed at app
  start; moving it into `.rehuco` (or an `.ini`, edited via a future fields-editor view) is deferred
  until it's actually needed, not designed now.
- **Borrow automation** — manual vs. automated power-down of the source box is unresolved
  ([[borrowing#another-instance-role]]).
- **Code-signing / notarization** (Apple Developer ID, Windows certificate) — an unpriced prerequisite for shipping
  *downloaded* installers and updates ([[packaging-deployment#auto-update]]), not yet committed. The file-association
  and app-identity *mechanics* are proven (see the resolved list above, [[appendices.briefcase-packaging#overview]]);
  signing is the remaining gap before a native installer a stranger downloads runs without Gatekeeper/SmartScreen
  friction. Does not affect `uv tool install` or the author's own machines.
- **First build slice** — not yet chosen.
- **Concrete technology stack** — PySide6 (+ `pyside6-scintilla`, `pyqtads` for docking — chosen over KDDockWidgets on
  licensing grounds, [[packaging-deployment#licensing-policy]] — selective QQuickWidget use for QML surfaces), SQLite +
  SQLAlchemy for the cache, FastAPI + HTMX + Pico CSS for the web UI, zeroconf for discovery, `uv` for environment
  management — strong candidates. The QNAP's old glibc (2.23) is no longer a deployment constraint — the TS-230 serves
  as a NAS over SMB and the node runs on capable hardware ([[packaging-deployment#ts230-as-nas]]); the 2026-06-30 canary
  confirmed all planned node dependencies (pydantic-core, cryptography, etc.) install and import on glibc 2.23 anyway
  ([[packaging-deployment#glibc-canary]]), keeping direct QNAP deployment viable if ever reconsidered. Stack not yet
  finalized.
- **File-size human-readable format** — not finalized. Implemented as GNU `ls -sh` style (base-1024, single-letter
  suffix, no space, e.g. `1.4G`) via `humanize.naturalsize(value, gnu=True)`, kept until decided otherwise — unlike
  duration ([[field-schema#duration-format]], settled), size ([[field-schema#duration-size]]) has no documented display
  convention. This happens to compute the same base as Windows Explorer's own size column (base-1024 math, just
  `KB`/`MB`/`GB`-style labels instead of GNU's bare letters); revisit if a different convention (decimal/SI, IEC
  `KiB`/`MiB`/`GiB`, or matching Explorer's own labels) turns out to be wanted.
