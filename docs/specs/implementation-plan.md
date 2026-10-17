# rehuco — Implementation Plan

[[[implementation-plan]]]

> [!NOTE]
> **Tracer-Bullet First Slices**
>
> Each feature area opens with a **tracer bullet** — the thinnest real, kept, production-grade path through
> every layer, proving they connect end-to-end. Later iterations thicken one part at a time without breaking
> the working spine. This counters the failure mode of building layers deeply in isolation before anything
> works as a whole.
>
> *Concept from [The Pragmatic Programmer](https://en.wikipedia.org/wiki/The_Pragmatic_Programmer)
> (Thomas & Hunt); further discussion at [wiki.c2.com](https://wiki.c2.com/?TracerBullets).*

Companion to `architecture-design.md`. What was planned and how it landed is in git history and each
package's `CHANGELOG.md`; this page tracks only what's still ahead, against the original personal
priorities:

1. View/edit local `.rehu` for tutorials and reference images — **done** (`rehuco-agent` 0.1.0–0.3.0).
2. Scan folders into a cached catalog and search it — close to the original tutcatalog — **done** (0.3.0).
3. Watch a tutorial from the agent and from a tablet's browser — **ahead**: the in-app player first, then the node's
   watch page ("Node" below).
4. Borrow a local copy for offline viewing on leave — **ahead** ("Borrowing" below).

## Methodology: agile cadence, tracer-bullet spines

[[[implementation-plan#methodology]]]

**Agile** and **tracer bullets** are not alternatives — agile is the *cadence* (short iterations, something
usable each cycle, adjust as you learn), tracer bullets are a *technical strategy* used within it (build a
thin, real, kept end-to-end skeleton through every layer first, then thicken). This plan uses **agile
iterations whose first slice of each feature area is a tracer bullet.**

Why tracer bullets specifically fit here:

- The risk is **integration, not features** — the architecture doc shows the features are understood;
  what's unproven is that the layers *connect* (the notifier into every view, a save as a job, the node beside the
  agent). **UI approach: both QML and QtWidgets**, each where it's strongest — QWidgets (with QtAds
  docking) for dense sortable/filterable tables and trees (the browsers, [[plugins#browsers]]) and the app
  shell; QML for the image grid and animated lightbox.
- It **counters the prior failure mode** — earlier versions built layers deeply (a full field/type system in
  TutCatalog5) without reaching a usable end-to-end whole. A tracer bullet keeps a usable-if-minimal thing
  alive from iteration one.
- Tracer bullets are **kept production code**, not throwaway prototypes — exactly the discipline wanted
  after three discarded attempts.

**Rule for every feature area:** the first iteration is the thinnest end-to-end path that *works and is
kept*. Later iterations thicken one part without breaking the working spine.

**The plan is a guide, not a contract — life beats any planning.** A slice grows, splits, and gains ad-hoc
features as implementation teaches. Introducing a feature ad-hoc when it's needed is expected, not a
deviation: the GH issues (grouped by category label, [[appendices.project-management#category-labels]]) are
the live record of what's actually being built, and this plan catches up after the fact. The most recent
example is the largest: the 2026-10-16 redesign ([[architecture-design#why-distributed]], #509) replaced
Release 0.4.0's swarm program wholesale, after the spikes it opened with (#502–#505) and the first node slice
(#506) had answered what the platforms allow.

### Spikes vs. tracer bullets (a related but different distinction)

A third term, **spike** (from XP), is often confused with a tracer bullet. They're distinguished by **what
you keep**, which follows from **what question each answers**:

- **Spike** — answers *"I don't know how/whether X works — let me find out."* Time-boxed, quick-and-dirty,
  **throwaway by intent.** Its product is *knowledge*; the code is deleted afterward (keep the lesson, not
  the toy).
- **Tracer bullet** — answers *"do my layers connect end-to-end?"* Minimal but **real, production-grade,
  and kept.** Its product is a *working skeleton* you build on.
- **Prototype** — like a spike (throwaway), but broader/UX-exploratory rather than one sharp technical
  question.

**The trap:** letting a spike quietly become load-bearing — building on quick-and-dirty exploration code
written *before* you understood the problem. Decide up front which you're writing and honor it. Quick test:
*"if this works, do I keep the code or just the lesson?"* Keep the code → tracer bullet (write it properly).
Keep the lesson → spike (write it fast and **delete it**).

**They sequence:** for a layer with genuine unknowns → **spike** (learn, discard) → **tracer bullet** (build
the thin real spine, now informed) → **thicken** (iterations). Skip the spike where there are no real
unknowns. **Spikes come before the spec**, where the spec would otherwise guess what a platform does: the
notifier and lock spikes (#502, #503) ran before [[sync#lock-file]] and [[mounts-and-storage#out-of-band]]
were written, and their measurements are what those sections state.

### Model strategy (Claude Code): `opusplan` backbone, manual escalation for the hard cores

[[[implementation-plan#model-strategy]]]

> [!NOTE]
> **Use `opusplan` as the default** (set `/model opusplan` at the start of each session). It ties model
> choice to mode: **Opus in plan mode** (architecture, edge cases, tradeoffs), then **automatically switches
> to Sonnet in execution mode** for code generation. For ~90% of rehuco — field widgets, UI wiring, web
> templates, migration tooling — this gives Opus-quality planning and Sonnet-speed execution with no
> micromanagement, and it's *better* than hand-switching for routine work.
>
> **Its one blind spot matters for this app:** `opusplan` switches on *mode*, not on *how hard the code is*.
> It assumes "execution = mechanical." But rehuco has a few cores where the *implementation itself* is
> reasoning-dense and a subtle error silently corrupts data. For those, **manually switch to Opus (`/model
> opus`) even while implementing** — context carries over, so you can drop back to `opusplan`/Sonnet after.
> These cores are marked with `> [!NOTE]` blocks in the specs; they are:
>
> - **The save path** — the lock file's stale rule, the compare-and-swap, the per-field merge and the
>   apply-payload job's coalescing ([[sync#overview]]).
> - **Plugin block save invariant** — the active/inactive/claim-then-abandon rule
>   ([[plugins#plugin-blocks]]).
> - **Cross-filesystem verified copy and move** — checksum-gated, resumable, data-loss-sensitive
>   ([[mounts-and-storage#safe-move-rename]]).
>
> Don't micro-manage beyond that — constant hand-switching for ordinary work wastes effort; the point of
> `opusplan` is to handle the common case so attention goes only to these few exceptions. Feeding the
> relevant section into context makes even Sonnet reliable on the routine parts and Opus more reliable
> on the hard ones. (Model names/aliases shift over time and by plan/provider — verify the current `/model`
> list in Claude Code; the *strategy* is stable regardless of version numbers.)

---

## Local edit — remaining work

The editor is built (`packages/rehuco-agent/CHANGELOG.md`), shortcut customization included. What's left is
filed: improved dark/light theming (#285), one System Integration page with platform frames (#508). See each
issue for the actual scope; this is only an index.

## Web scrapping — remaining work

Scraping itself is built (`packages/rehuco-agent/CHANGELOG.md`). What's left is filed: an image picker for
a page or selection dropped on the images sub-dock (#275) and a console-only CLI companion app so
`--scrape`/`--scrape-schema` work from a packaged install (#346).

## Cache DB — built; the notifier is next

**Goal:** point the agent at your folders, have it scan the `.rehu` files into a `.rehudb` cache, and
browse/search the catalog on the desktop — close to the original tutcatalog. The cache is a rebuildable derivative of
the `.rehu` files, never a source of truth ([[data-model#local-file-trio]]).

**Status:** the tracer bullet (#377) and its thickening run — open a `.rehuco`, scan, filter, and click through to view
or edit any resource, with the cache following the app's own saves and renames; a change made outside the app shows
after the next scan. What remains is filed: the image browser (#403), nested roots refused (#498), and the two slices
the redesign added:

- **The file notifier** ([[mounts-and-storage#out-of-band]]): `FileNotifier` in core with the native, SMB-session and
  polling backends, publishing on `ChangeFeed`; the agent's views listen to it alone, and `RootCatalog`'s own derived
  signals and the never-announcing writers go. Then every machine follows every other without a scan.
- **The shareable `.rehuco`** ([[mounts-and-storage#rehuco-scope]]): a location and per-machine mappings per root, the
  storage kind detected, the mapping wizard, unmapped roots disabled.

Root caching (#449–#451) follows, unchanged by the redesign.

## Saves — the lock, the compare, the job

**Goal:** two agents on one share, a web user writing progress through a node, and someone editing a file by hand are
kept apart with no silent overwrite ([[sync#overview]]).

**Tracer bullet:** the lock file and the compare-and-swap in `LocalRecords.save` (and `merge_write`), `.lock` excluded
from scans, checksums and renames, a two-process test on one folder.

Then thicken: the apply-payload job on the task queue (#497 rewritten) with its persisted payload, coalescing, Pending
saves filter and status counter, Inspect into the conflict dialog; then the per-user sidecar
([[data-model#single-file]]) with its format version, the one-time migration of the `users` maps, and the conflict
dialog over both files.

**Exit criteria:** two agents save the same record; exactly one wins, the other lands in Pending saves with a correct
three-way diff; a lock older than the TTL is broken with a log line; a progress write while the record is edited
elsewhere produces no conflict.

## Node — the agent's child, then the web pages

**Goal:** watch a tutorial from the agent or from a tablet's browser with progress following between them
([[nodes#overview]]).

**Done:** the tracer bullet — the node as a heartbeat process the agent hosts, the Local node block and the status bar
indicator (#506).

Then, in order: the in-app player and external VLC (#315–#319) over watch progress in core (#410, #411); the FastAPI +
HTMX + Pico spike (#418); the web node — login by OTP (#422 rewritten), the tutorial list and the watch page writing the
user's sidecar (#440, #441), media with Range (#433), the conversion cache that remuxes or transcodes the file a browser
cannot play ([[nodes#web-playback]], measured by the iPad playback spike, #419), *Open local node* and the remote
serving node (#437 rewritten); the Nodes view with jobs by user, CPU and memory (#435 rewritten); the system-service
opt-in only if ever wanted (#439, the recipe on #504).

**Exit criteria:** watch 10 minutes in the agent, 15 on the tablet through a node, and resume in the agent at 25.

## Borrowing

**Goal:** borrow a tutorial onto the machine that travels, watch it with everything at home off, and return it with its
progress reconciled ([[borrowing]]).

In order: the resumable verified copy (#339 rewritten); the node's borrow store and a local borrow with its `.borrow`
record, the UUID check against reachable nodes with per-node snapshots, and the Borrowed window; the Storage view; a
borrow onto another machine's node over HTTP; Return as apply-payload jobs, per user and admin-for-all; scheduled
archival (#448) stays deferred. Hash delegation to a node with local disk access is the optional last slice
([[nodes#node-status]]).

**Exit criteria:** borrow a tutorial onto the mini, watch it with the PC and the NAS off, and return it with its
progress reconciled.

## Reference images — richness not started

Viewing and editing a reference-images resource is done and genuinely usable: the resource type, its
fields, checksums, and the **Content Images** dock (#221 — a grid over a pack's archive members and, since #392,
its loose images, a decode-on-demand lightbox) all shipped. What's unbuilt is the *richness* layer on top:
the `.rehuimg` sidecar skeleton, a `rehuco-vision` inference package, redaction (blur, per-user overrides,
a region sub-dock, the scope cascade, a cover/inpainting effect), tagging and embeddings, a Pinterest-style
in-pack and cross-pack search, and pose-driven ranking ([[reference-images]]). This is its own wave of GH
issues (category `reference images`); the current sequencing lives in the work queue and on those issues
rather than here. Order decided at filing: sidecar and vision skeleton first, then **redaction** and **search**
interleave; 360° identification and practice mode are deliberately last.

## Deferred

- **LLM URL extraction** — [[acquisition-tooling#llm-url-extract]], a fallback for hosts no scraper
  matches. Deferred until a real run of unmatched hosts says it's worth a model; a user-written scraper
  covers the gap meanwhile.
- **3D objects, a dedup review UI, an access-rule grammar, web for non-tutorial types.**
- **Auto-update** — the installers themselves landed (#206,
  [[appendices.briefcase-packaging#status]]): Briefcase-built installers with declarative file
  association/icon/AUMID. MSIX packaging and self-update against a public release oracle still wait on
  code-signing/notarization ([[packaging-deployment#app-identity]]/[[packaging-deployment#auto-update]]).
- **A system-service node** — measured, costed and set aside ([[nodes#overview]], #504).
- **The macOS own-session and Linux legs of the notifier and lock spikes** (#502, #503) — until a mobile macOS or
  Linux box is in daily use.
- **Daz3D library migration** — its own further-out effort.

## Sequencing gates still open

- **Before the node's web pages (#418):** a short FastAPI/HTMX/Pico **spike**, since it's a new stack — answer
  "can the watch page be built the way it's needed", keep the lesson, discard the toy.
- **Before the apply-payload job:** the lock and compare in the save path, which it wraps ([[sync#overview]]).
- **Before Borrowing:** the resumable verified copy (#339) and the apply-payload job, which Return is a batch of.

## Honest caveats

- The prior versions de-risked **design** more than they supplied droppable code — only the oldest
  (TutCatalog4, C++/Qt5) reached "usable," and the Python ones were ideas/scaffolding to redesign
  (see [project history](history/README.md)).
- Nothing above is estimated in dev-time; the size a piece of work turns out to be is tracked on its GH
  issue (`XS`–`XL` labels, [[appendices.project-management#category-labels]]) once it's actually filed.
