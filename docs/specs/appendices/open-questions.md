# Open Questions — Out of Scope and Not Yet Designed

[[[appendices.open-questions]]]

## Overview

[[[appendices.open-questions#overview]]]

Flagging gaps so they're a deliberate choice rather than an oversight.

## 1. Resolved or scoped since the first consolidation

[[[appendices.open-questions#resolved-or-scoped]]]

Many of the entries below were first resolved *inside the swarm design* and resolved again, differently, when that
design was dropped on 2026-10-16 (#509, [[appendices.post-mortem#architecture]]). Each names what settles it today.

- **Metadata-conflict during offline editing** — resolved twice. First by making metadata online-only-editable under
  a single writer; now there is no single writer and no sync engine: a save takes the record's lock, compares the file
  with the version the edit was based on, and shows a conflict rather than losing an edit ([[sync#overview]]). Details
  are still editable only while the file is reachable; per-user edits made offline wait as queued saves
  ([[offline-editing#overview]]).
- **Known copies / offline-instance persistence** — the rebuild-from-scratch model was imprecise, then bounded
  ([[architecture-design#why-distributed]]): retained metadata copies ([[mounts-and-storage#durable-retention]])
  survive rebuild by rescan; a borrow is recorded beside its copy in a `.borrow` file ([[borrowing#recording-borrows]]).
  The instance registry that was to track the rest is gone ([[instances-and-dedup#instance-registry]]).
- **Per-image metadata location** — clarified ([[data-model#image-meanings]]): app-managed mutable metadata alongside
  `.rehu`, never inside the immutable checksummed zip. Now given a concrete shape ([[reference-images#layers]]):
  machine-derived output in a scan sidecar beside the `.rehu`, an admin-authored default inline in the block,
  per-user overrides in the user's sidecar; keyed by the zip's own central-directory identity with XXH3 as the
  durable key ([[reference-images#image-identity]]). What a node needs for scanning versus serving, and how scans
  are dispatched, are [[reference-images#node-requirements]] and [[reference-images#dispatch]].
- **Scanning strategy** — incremental, version-aware reconciliation is the normal mode, the file notifier reports
  changes as they happen, and full rescan is demoted to recovery ([[data-model#scan-and-staleness]],
  [[mounts-and-storage#out-of-band]]). The earlier "no disk watcher" policy is reversed.
- **Node identity, pairing, membership, registry home, serve-after-resync** — all retired with the swarm: nodes do not
  talk to each other ([[discovery-trust-access]]).
- **App/filesystem coupling** — resolved twice: first the agent as a node client, then #409's local-first agent with
  an access seam for node-owned roots, and now the agent reads and writes every file itself over its mounts; the seam's
  remote half is torn down and its local classes stay ([[nodes#access-seam]]).
- **Cross-machine storage topology** — a root's machine-independent location and per-machine mappings in the
  `.rehuco`, resolved through each machine's mount table ([[mounts-and-storage#rehuco-scope]]); fingerprint files and
  the primary/remote flag are retired.
- **Deletion / tombstone propagation** — a deleted record is a filesystem fact the notifier reports; there are no
  tombstones ([[sync#compare-and-swap]]). Borrow-vs-delete/archive has an explicit resolution on return
  ([[borrowing#borrow-vs-delete]]).
- **Clock skew / ordering** — mostly moot: nothing orders events across machines; the save compares content hashes,
  never times ([[sync#compare-and-swap]]). The one place a clock crosses machines is the lock file's stale rule
  ([[sync#lock-file]]): a contender more than the TTL (2 minutes) *ahead* of the holder's clock would break a lock
  still held. The compare then still refuses the lost update; the lock only narrows the window. Not tuned until a
  machine with a drifting clock joins.
- **Per-user authentication** — a one-time password issued by the node's CLI for a username, exchanged for a per-device
  session; no password store, nothing propagated; the agent itself needs no login
  ([[discovery-trust-access#user-auth]]).
- **Visitors / sharing** — a guest is an ordinary web user; sharing content is a copy stripped of sidecars, locks and
  borrow records ([[discovery-trust-access#cross-swarm-sharing]]).
- **Access control model** — rules are the node's own, enforced at the node for what it serves, with tag-grants
  evaluated dynamically ([[discovery-trust-access#access-control]]). Remaining work is the concrete representation.
- **Local file layout** — `.rehuco` (shareable, per-machine mappings), `.rehudb` (disposable cache, per machine), the
  retention store (durable); no `.rehusw` ([[data-model#local-file-trio]]). Per-user state is a sidecar beside the
  record ([[data-model#single-file]]).
- **Single-machine / bootstrap operation** — an agent with the share mounted and no node is a complete rehuco
  ([[multiplicity#single-node-base]]); nothing waits for peers.
- **Node vs. agent split** — the node is the agent's child, running as the agent's user, with no roots of its own; it
  serves the user's reachable roots and its borrow store, and stops with the agent ([[nodes#two-roles]]). A system
  service was measured and set aside ([[nodes#overview]]).
- **App readiness / responsiveness** — resolved ([[nodes#readiness-per-op]]): per-operation readiness, not one global
  gate; local-file and cached operations never block; the share is waited for in the task queue.
- **Local-file vs. catalog mode / no-node viewing** — resolved ([[nodes#local-vs-swarm]]): the single-file viewer
  needs no catalog, no node and no login; the catalog enriches when open.
- **Single-instance & file association** — resolved ([[nodes#single-instance]]): bind-or-forward single-instance, one
  main agent hosts both scopes, stale-socket reclaim, socket scoped per OS user and per settings folder; an accepted
  close always quits explicitly (#507).
- **Login persistence** — a per-device session the node remembers ([[discovery-trust-access#user-auth]]); revocation
  is the CLI's.
- **`.rehu` write integrity** — resolved ([[data-model#write-integrity]]): universal atomic temp-then-rename, the
  exclusive-create lock file, compare-and-swap on content hash; every writer equal, saves as jobs
  ([[sync#apply-payload]]).
- **`.rehu` schema format versioning** — resolved ([[data-model#schema-version]]): per-file format-version field; newer
  reader upgrades older files, older reader preserves unknown fields rather than dropping them.
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
- **Acquisition & migration tooling** — specced ([[acquisition-tooling#overview]]): three drops (HTML→Markdown,
  image→screenshot, URL→fields), user-overridable site-scraper Protocols with a deferred local-LLM fallback
  ([[acquisition-tooling#url-extract]]), `.tc`→`.rehu` migration (landed). The drops and scrapers are the
  **WebScrapping** family ([[acquisition-tooling#deferral]]).
- **Code organization, packaging & deployment** — resolved ([[packaging-deployment#overview]]): monorepo with uv
  workspaces (single `.venv` fixes the venv-confusion and makes cross-package refactors atomic); three published
  packages (`rehuco-core`, `rehuco-node`, `rehuco-agent`); the TS-230 serves as a NAS over SMB and is the system of
  record ([[packaging-deployment#ts230-as-nas]]), so the glibc constraint is moot (canary findings kept in
  [[packaging-deployment#glibc-canary]] for reference).
- **Offline revocation limitation** — acknowledged as a deliberate accepted boundary
  ([[discovery-trust-access#serve-after-resync]]): a borrowed copy in hand cannot be revoked; an admin returns it for
  everyone the next time its machine is reachable.
- **Desktop distribution, file association & app identity** — analyzed
  ([[packaging-deployment#app-identity]]/[[packaging-deployment#auto-update]]): the agent is dual-channel (`uv tool` for
  the author's own machines/devs; a native installer for wider reach); file association is OS-specific with macOS as the
  binding constraint; Windows taskbar identity is an identity-registration matter, not a reason to freeze the app;
  **Briefcase** is chosen for end-user installers over PyInstaller, with MSIX a possible later upgrade; auto-update
  checks a public version oracle and delegates installation to the platform installer. All wider-distribution polish,
  off the personal critical path. **The Linux format is settled too** ([[packaging-deployment#linux-format]]):
  Linux ships no package — `uv tool install` plus the desktop entry the app writes (#209) — with Flatpak, Snap and
  AppImage each ruled out on a verified ground, and Linux association turning out to be the app's own job rather than
  Briefcase's ([[appendices.briefcase-packaging#linux-backends]]).

## 2. Still open

[[[appendices.open-questions#still-open]]]

- **Full `.rehu` schema** — field ownership (common vs. plugin) is settled ([[data-model#rehu-format]],
  [[plugins#core-vs-plugin]]); the complete field list/types per plugin is being designed separately. Archival is a tag
  ([[borrowing#scheduled-archival]]), not a schema state.
- **Access-rule representation** — the model is settled ([[discovery-trust-access#access-control]]: per node,
  server-enforced, full/per-resource/dynamic-tag grants); how a grant is written and how grants combine is not.
- **What converts a video for the web** — playback and the conversion rules are decided ([[nodes#web-playback]]); the
  tool is not: an `ffmpeg` executable the user supplies, as the duration probe already accepts, or PyAV, whose wheel
  bundles `libx264`, `libx265`, `libdav1d` and the NVENC, QSV and AMF encoders but puts GPL code inside the installers.
  Also open: whether the certificate names the node's IP, its `.local` name or both, and how often Safari forgets an
  accepted certificate.
- **The lock's TTL and jitter** — 2 minutes and a few tens of milliseconds to start ([[sync#lock-file]]); tuned once
  two agents run on the share daily.
- **Which node runs a job** — permissions are per node and the Benchmark result is stored ([[nodes#node-status]]);
  how delegation weighs a stored benchmark against a root being local to the node, how old a benchmark may be, and
  what a headless node's config holds beyond the `.rehuco` path and machine name, are decided with the web node tracer.
- **Renamed machines and the `.rehuco` mappings** — the wizard's *this is the same machine as X* is specified, not
  built ([[mounts-and-storage#rehuco-scope]]).
- **The macOS own-session and Linux legs of the notifier and lock spikes** (#502, #503) — deferred until a mobile
  macOS or Linux box is in daily use; the design states what they would confirm (stored credentials, polling until
  given) and the Windows and macOS-client measurements already cover the primitives.
- **Remote (off-LAN) access** — *deliberately out of scope, not a gap.* The whole trust/discovery model
  ([[discovery-trust-access]]) is
  LAN-local by design. The app provides no remote-access mechanism and will not put a personal media catalog on the
  public internet. A user who needs access from outside, without standing up their own mobile node, should **VPN into
  the home network** (WireGuard/Tailscale/etc.) — at which point they are "on the LAN" and everything works unchanged.
  This cleanly delegates remote-access security to mature purpose-built software instead of reinventing it in the app;
  the app stays simple and LAN-trusting, the VPN decides who may reach the network at all.
- **Export/import mechanics** — the rules are decided (keep UUID, strip sidecars, `.lock` and `.borrow`,
  [[discovery-trust-access#cross-swarm-sharing]]); the concrete export shape and the import-side UUID-collision handling
  aren't designed.
- **Online-only and mixed local/online resources** — needs schema representation; not detailed.
- **Udemy integration** — registered courses are hard to track. A Udemy page scraper is a built-in of
  [[acquisition-tooling#scraper-registry]]; an account-side import of *what the user owns* is not discussed.
- **3D objects as a resource category** — mentioned alongside Daz3D but not mapped to a plugin design.
- **Shared timed-presentation capability** — identified as worth extracting ([[plugins#shared-capability]]) but not
  designed.
- **Drawing comparison/critique pipeline** — exploratory ([[plugins#refimages-plugin]]); needs prototyping before being
  committed.
- **Reference-image scanning — the parts left open** ([[reference-images#open-questions]] keeps the local list):
  the region/blur sub-dock's interaction design; the scan sidecar's final name and whether SQLite holds; the
  tag-vocabulary mapping for a user-supplied tagger; mixed-model embeddings (refuse to merge, or one index per
  model); whether a serving node carries the query text encoder or delegates encoding; the working-image
  storage budget; practice-session retention; what 360° sequences are for.
- **Where a type's *ordered* field list is authored** — narrowed, not closed. *Which* fields a type has is settled:
  the **plugin declares them** beside its key list ([[field-schema#resource-types]], #195), which is the half that
  decides what renders where. What is still open is where the **order** comes from — today one hardcoded Python list
  spanning every type, filtered per type, since the declarations are sets. `.rehuco` already declares which plugins
  load per machine ([[mounts-and-storage#rehuco-scope]]) but says nothing about field lists. The original
  tc5/resource-hub idea was to declare field lists **in `.rehuco` itself**, so different `.rehuco` files (spanning
  different root folders) could define different field sets for the same type — one machine/root's "Tutorial" need not
  match another's. That idea now applies to the ordering (and to *overriding* a plugin's declaration per root, if that
  is ever wanted); moving it into `.rehuco` (or an `.ini`, edited via a future fields-editor view) is deferred until
  it's actually needed, not designed now. Note this concerns **content** fields only: the `path`
  field is a location control, not a payload value, and is authored out-of-band regardless of where
  content field lists end up living ([[plugins#field-toolkit]]'s content-vs-location distinction).
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
  SQLAlchemy for the cache, FastAPI + HTMX + Pico CSS for the web UI (spiked, #418, [[nodes#web-pages]]), zeroconf for
  discovery, `uv` for environment management — strong candidates; no node-to-node protocol exists to choose for. The
  QNAP's old glibc (2.23) is no longer a deployment constraint — the TS-230 serves
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
- **Own the QtAds binding?** (estimated 2026-10-10; filed as #524, which #525's move to PySide6 6.12 needs unless a
  6.12 `pyside6-qtads` appears first) Forking Qt-Advanced-Docking-System and writing a shiboken binding
  on the `pyside6-scintilla` template (scikit-build-core, `cibuildwheel` ×4, stubs) is ~8–14 h to parity; the
  workarounds then go one by one, `QtAdsPinGuard` (#491) and `QtAdsEmptyingGuard` (#493) among them. `pyside6_qtads` is
  obsolete, not a base. `QMainWindow` + `QDockWidget` instead is ~10–15 h and loses pinning. Not urgent until a QtAds
  bug Python cannot work around, a PyPI `pyside6-qtads` lagging PySide6 or Python, or plugin tabs needing C++.
  Unverified: whether `dropIntoContainer`/`dropIntoSection`, which search recursively like #491's case, misplace
  nested docks.
- **Identity collapse on import** — imports file per-user state under `unknown` while the viewer reads the current
  identity, so a converted resource shows no learning paths until the two agree (#189). Whether this is *the*
  migration flow is undecided.
- **The multi-file manifest block may answer nothing asked** — reference images don't need it (#197), its last caller
  ([[daz3d-personal-database#multi-part]]) has the opposite shape, and a standalone `<stem>.rehu` describes one file
  ([[data-model#single-file]]). Decide, then file.
- **`public` is reserved by convention only** — nothing refuses it as the identity ([[field-schema#per-user-shared]]).
- **A location is a name; where it lives is a separate axis** (#322) — "which root or node" is its own control, or the
  move step (#339, #443), not more Locations rows.
- **`type:` and a `folder:` root label fold ASCII only** (SQLite `NOCASE`), while free text and
  `authors`/`tags`/`publishers` fold case and diacritics since #475.
- **The history pages' missing rows** (#471) — the tag/author/publisher/learning-path tree, the rename that rewrote
  every `info.tc`, filters by collection and saved searches are decided ([[plugins#tag-browser]],
  [[sync#value-rename]]); still open are TutCatalogPy2's include/exclude clicks, filters by path or flag, and
  TutCatalog5's user-editable fields ([[plugins#core-vs-plugin]]). Decide, then file.
- **A checksum file with no rehu** defaults to a disabled *Verify old checksums* (#457), so a double-click does
  nothing; whether Open is the fallback is undecided.
