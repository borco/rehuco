# rehuco — Implementation Plan

[[[implementation-plan]]]

> [!NOTE]
> **Tracer-Bullet First Slices**
>
> Each milestone opens with a **tracer bullet** — the thinnest real, kept, production-grade path through every
> layer, proving they connect end-to-end. Later iterations thicken one part at a time without breaking the
> working spine. This counters the failure mode of building layers deeply in isolation before anything works
> as a whole. A1, B1, and C1 are the tracer bullets; everything else thickens them.
>
> *Concept from [The Pragmatic Programmer](https://en.wikipedia.org/wiki/The_Pragmatic_Programmer)
> (Thomas & Hunt); further discussion at [wiki.c2.com](https://wiki.c2.com/?TracerBullets).*

Companion to `architecture-design.md`. This plan covers the **near-term build** scoped to the stated personal
priorities:

1. View/edit local `.rehu` for basic tutorials and reference images.
2. Watch a tutorial from a tablet/local browser.
3. (later) Borrow a local copy for offline viewing on leave.

## Before you create the monorepo (one-time, cheap-now/costly-later)

These are settled; listed so nothing is forgotten at `uv init`:

- **Name: `rehuco`** (decided). It propagates into package names (`rehuco-core`, `rehuco-node`, `rehuco-agent`), PyPI
  namespace, import paths, file extensions (`.rehu`/`.rehuco`/`.rehudb`/`.rehusw`), config dirs, and the swarm-ID scheme
  — which is exactly why it's chosen before init.
- **Reserve PyPI names** via throwaway `0.0.0` stub repos (the same move used for `pyside6-scintilla`/`-lexilla`): claim
  `rehuco`, `rehuco-core`, `rehuco-node`, `rehuco-agent` before anyone squats them.
- **Root `pyproject.toml` is a *virtual* workspace** — no `[project]` table, only `[tool.uv.workspace]`
  ([[packaging-deployment#three-packages]]). Decided.
- **`rehuco-node` `requires-python` floor** — set at creation; no constraint from the TS-230 since the node runs on
  capable hardware ([[packaging-deployment#ts230-as-nas]]).
- **Fresh git history** — start clean, old repos kept read-only as archive ([[packaging-deployment#migrating-repos]]).
  Decided.

## Methodology: agile cadence, tracer-bullet spines

[[[implementation-plan#methodology]]]

**Agile** and **tracer bullets** are not alternatives — agile is the *cadence* (short iterations, something usable each
cycle, adjust as you learn), tracer bullets are a *technical strategy* used within it (build a thin, real, kept
end-to-end skeleton through every layer first, then thicken). This plan uses **agile iterations whose first slice of
each milestone is a tracer bullet.**

Why tracer bullets specifically fit here:

- The risk is **integration, not features** — the architecture doc shows the features are understood; what's unproven is
  that the layers *connect* (agent↔node client split, the field/block model rendering end-to-end). **UI approach: both
  QML and QtWidgets**, each where it's strongest — QWidgets (with pyqtads docking) for dense sortable/filterable tables
  and trees (the browsers, [[plugins#browsers]]) and the app shell; QML for the image grid and animated lightbox. This
  needs the pyqtads-hosts-QML integration to hold (the spike below). Note: the "NVIDIA overlay" prompt seen on app start
  is the GeForce/NVIDIA App **in-game overlay** reacting to the GPU context — a per-machine NVIDIA-software setting to
  toggle off, *not* an app concern and not a rendering problem; it imposes no architectural constraint.
- It **counters the prior failure mode** — earlier versions built layers deeply (a full field/type system in
  TutCatalog5) without reaching a usable end-to-end whole. A tracer bullet keeps a usable-if-minimal thing alive from
  iteration one.
- Tracer bullets are **kept production code**, not throwaway prototypes — exactly the discipline wanted after three
  discarded attempts.

**Rule for every milestone:** the first iteration is the thinnest end-to-end path that *works and is kept*. Later
iterations thicken one part without breaking the working spine.

**The plan is a guide, not a contract — life beats any planning.** Slices grow, split, and gain ad-hoc features as
implementation teaches (A2 already did; see its sub-slices on the GH milestone). Introducing a feature ad-hoc when
it's needed is expected, not a deviation: the GH milestones/issues are the live record of what a milestone actually
contains, and this plan catches up after the fact.

### Spikes vs. tracer bullets (a related but different distinction)

A third term, **spike** (from XP), is often confused with a tracer bullet. They're distinguished by **what you keep**,
which follows from **what question each answers**:

- **Spike** — answers *"I don't know how/whether X works — let me find out."* Time-boxed, quick-and-dirty, **throwaway
  by intent.** Its product is *knowledge*; the code is deleted afterward (keep the lesson, not the toy).
- **Tracer bullet** — answers *"do my layers connect end-to-end?"* Minimal but **real, production-grade, and kept.** Its
  product is a *working skeleton* you build on.
- **Prototype** — like a spike (throwaway), but broader/UX-exploratory rather than one sharp technical question.

**The trap:** letting a spike quietly become load-bearing — building on quick-and-dirty exploration code written
*before* you understood the problem. Decide up front which you're writing and honor it. Quick test: *"if this works, do
I keep the code or just the lesson?"* Keep the code → tracer bullet (write it properly). Keep the lesson → spike (write
it fast and **delete it**).

**They sequence:** for a layer with genuine unknowns → **spike** (learn, discard) → **tracer bullet** (build the thin
real spine, now informed) → **thicken** (iterations). Skip the spike where there are no real unknowns.

In this plan, **A1/B1/C1 are tracer bullets** (kept spines). The items flagged *(spike)* below are throwaway — keep the
lesson, delete the code.

### Model strategy (Claude Code): `opusplan` backbone, manual escalation for the hard cores

[[[implementation-plan#model-strategy]]]

> [!NOTE]
> **Use `opusplan` as the default** (set `/model opusplan` at the start of each session). It ties model choice to mode:
> **Opus in plan mode** (architecture, edge cases, tradeoffs), then **automatically switches to Sonnet in execution
> mode** for code generation. For ~90% of rehuco — field widgets, UI wiring, REST endpoints, web templates, migration
> tooling — this gives Opus-quality planning and Sonnet-speed execution with no micromanagement, and it's *better* than
> hand-switching for routine work.
>
> **Its one blind spot matters for this app:** `opusplan` switches on *mode*, not on *how hard the code is*. It assumes
> "execution = mechanical." But rehuco has a few cores where the *implementation itself* is reasoning-dense and a subtle
> error silently corrupts data. For those, **manually switch to Opus (`/model opus`) even while implementing** — context
> carries over, so you can drop back to `opusplan`/Sonnet after. These cores are marked with `> [!NOTE]` blocks in
> `architecture-design.md`; they are:
>
> - **Sync engine** — version vector + activity log, conflict/merge, tombstones ([[sync#overview]]).
> - **Plugin block save invariant** — the active/inactive/claim-then-abandon rule ([[plugins#plugin-blocks]]).
> - **Registry resolution & serve-after-resync** — preferred-authority/chatter, version-marker comparison
> ([[discovery-trust-access#registry-home]], [[discovery-trust-access#serve-after-resync]]).
> - **Cross-filesystem safe move** — checksum-gated, data-loss-sensitive ([[mounts-and-storage#safe-move-rename]]).
>
> Don't micro-manage beyond that — constant hand-switching for ordinary work wastes effort; the point of `opusplan` is
> to handle the common case so attention goes only to these few exceptions. Feeding the relevant `§` section into
> context makes even Sonnet reliable on the routine parts and Opus more reliable on the hard ones. (Model names/aliases
> shift over time and by plan/provider — verify the current `/model` list in Claude Code; the *strategy* is stable
> regardless of version numbers.)

---

## Pre-work (do before/around the first slice)

These unblock or de-risk everything after; small but high-leverage.

| Task | Kind | Why now | Notes |
| --- | --- | --- | --- |
| Stand up the monorepo (uv workspaces) | setup (kept) | The dev environment for everything; fixes the venv-confusion immediately ([[packaging-deployment#overview]]) | Root virtual workspace + `packages/rehuco-core`, `apps/rehuco-agent`; add `rehuco-node` later when Milestone B starts |
| Decide the **tutorial** and **reference-image** field lists | decision | Specific-field rendering is the one thing blocked on schema ([[appendices.open-questions#still-open]]) | The generic editor does *not* need this; only the rich per-type view does. Decide enough to start, refine later |
| Decide access-rule grammar | decision | Not needed for Milestones A/B (single user, local) | Can defer to Milestone C-ish; noted so it's not forgotten |
| **pyqtads + QML integration (regression check)** | **spike** | Confirms the "both QML and QtWidgets" approach still holds on current Qt/PySide6/pyqtads versions | QML-in-pyqtads already worked previously; this re-verifies it on current versions, focused on the parts the app will depend on: a QQuickWidget dock that **detaches to a floating window and re-docks** without glitches (the classic QML cross-window trouble spot), a **QWidgets dock and QML dock coexisting** in one layout, and **layout save/restore** with a QML dock present — including **whether closed/hidden docks restore their size** (a known soft spot across all Qt docking; likely needs stashing dock size on close keyed by object name and restoring on show, rather than relying solely on the layout blob). Keep a tiny reference snippet of the working wiring; discard the rest. If a QML dock's detach glitches, the response is to **keep QML surfaces in non-detachable docks or reduce the QML footprint** — *not* switch to KDDockWidgets, which is foreclosed by its GPL license (architecture [[packaging-deployment#licensing-policy]]). pyqtads stays (LGPL, prebuilt PySide6 bindings). **Result:** approach holds on PySide6 6.11.1 + pyside6-qtads 5.0.0; one caveat — a closed dock's size needs a `splitterSizes` stash/reapply workaround — carried forward — it landed with the A2.0 document-dock shell (#20). Recorded in [[packaging-deployment#qml-regression]] |
| **QNAP/glibc dependency canary** | **spike** | De-risks Milestone B's node deps early | Build a glibc-2.23 container; confirm FastAPI/uvicorn/zeroconf/pydantic-core/cryptography wheels load. Keep the lesson (a pinned compatible-versions list); the container/script is throwaway |
| **File association + app identity** | **spike** | De-risks A1's "double-click → opens" before A1 depends on it ([[packaging-deployment#app-identity]]) | macOS: a minimal `.app` (built via Briefcase) that's the default opener for `.rehu` and delivers the path as a **`QFileOpenEvent`** into a single running PySide6 instance ([[nodes#single-instance]]) — macOS does *not* pass it as `argv`. Windows: an HKCU **ProgID** for default double-click + an explicit **AUMID** (`SetCurrentProcessExplicitAppUserModelID`) so a pinned taskbar button shows the app's icon and lights up as running (the gap `resource-hub` only papered over with a PyInstaller exe), with `DefaultIcon` from a shipped `.ico`. Second double-click routes to the existing instance, not a new process. Keep the bundle/ProgID recipe + AUMID line; discard the toy GUI. Confirms Briefcase as the end-user packager as a side effect |

---

## Milestone shape at a glance

The three near-term milestones map one-to-one onto the personal priorities above, ordered so each **climbs exactly one
rung up the distribution ladder** and introduces exactly **one new architectural spine** — isolating integration risk
(the architecture's thesis is that the risk is *integration, not features*).

| | **A — Local view/edit** | **B — Watch from a tablet** | **C — Borrow offline** |
| --- | --- | --- | --- |
| **Use-case** | View/edit a local `.rehu` | Watch a tutorial from a browser | Borrow a copy, watch offline |
| **Topology** | 1 machine, no network | 1 node + thin browser clients (LAN) | 2 parties (home node ↔ laptop) |
| **New spine** | Field/block/plugin rendering + local file I/O | The node + agent-as-node-client refactor ([[nodes#two-roles]]) + web stack | Version-vector + activity-log sync ([[sync#overview]]), two-party |
| **Deliberately absent** | No node, swarm, or login | No swarm, pairing, multi-node sync, or auth-propagation | No general swarm — just two-party reconcile |
| **New skill / risk** | Rendering the data model end-to-end | Web stack (FastAPI/HTMX/Pico), SQLite cache, video serving | Conflict/merge machinery |

Three principles hold across the split:

- **Monotonically increasing distribution complexity.** A is standalone (no network); B adds a single node serving thin
  clients; C adds two-party sync — the first real reconcile, but the minimal topology. The full **N-node swarm**
  (discovery, pairing, registry, safe-move — [[discovery-trust-access]],
  [[mounts-and-storage#fingerprint-map]]–[[mounts-and-storage#safe-move-rename]]) is deferred *past* all
  three.
- **One new integration risk per milestone.** Each isolates a single unproven spine so nothing tackles two at once;
  within each, the first slice (A1/B1/C1) is a kept **tracer bullet** and the rest thicken it.
- **Each is independently useful and shippable.** A is a standalone tool even if B/C never ship; B adds tablet watching;
  C adds offline borrow. Value lands at every milestone boundary.

Everything heavier — full swarm, acquisition/LLM tooling ([[acquisition-tooling#overview]]), reference-image richness,
Daz3D, multi-user auth, native installers — is deliberately parked past C (see
[What is deliberately deferred](#what-is-deliberately-deferred-past-these-three)).

---

## Versioning & releases

Version numbers follow the milestones for the shipped **apps**, but the reusable **libraries** version independently —
because a version number is a compatibility contract only for code other projects *import*.

- **`rehuco-agent`, `rehuco-node`, and `rehuco-core`** — **MAJOR = the number of completed milestones.** `0.x` while
  Milestone A is being built → **`1.0` when Milestone A is complete** (the standalone local tool) → `1.x` through B →
  **`2.0`** when B is complete → **`3.0`** when C is complete. **MINOR = a shipped slice** within the in-progress
  milestone (slice `A2` → `0.2`, `A3` → `0.3`, …); **PATCH** = fixes. These three release **in lockstep**; `rehuco-node`
  simply has no releases until Milestone B, then joins at `1.x`, staying aligned with the agent. Treating MAJOR as
  "milestone" rather than "breaking change" is acceptable **only because these have no external API consumers** — the
  apps are end-products and `rehuco-core`'s only consumers are the in-repo apps. If `rehuco-core` ever gains external
  consumers, it splits off to independent SemVer (below).
- **`borco-core`, `borco-pyside`** — generic, reusable, and slated to move to their own repository
  ([[packaging-deployment#three-packages]]), so they *will* have external consumers → **ordinary, independent SemVer**,
  decoupled from rehuco's milestones. They stay in `0.x` with `0.y` as the compatibility unit (bump **MINOR** `y` for a
  breaking or notable change, **PATCH** `z` for a fix), and reach **`1.0` on the move-out**, when the public API is
  frozen. A new `borco-*` release is published alongside a rehuco release only when the library actually changed.

| Milestone complete | `rehuco-agent` / `-node` / `-core` | `borco-core` / `-pyside` |
| --- | --- | --- |
| A | `1.0` | independent `0.y` → `1.0` on move-out |
| B | `2.0` | independent |
| C | `3.0` | independent |

Automated PyPI publishing is tracked in issue #18 and is not yet wired up — every package is a `0.0.0` stub until then,
so this policy is recorded now and applied at first publish.

---

## Milestone A — Local view/edit (no node, no swarm, no login)

**Goal:** a standalone, usable tool that opens, displays, and edits a local `.rehu` for tutorials and reference images.
This is the agent's local-file mode ([[nodes#local-vs-swarm]]), and a genuinely useful product on its own.

### A1 — Tracer bullet (the spine)

> Double-click a `.rehu` in File Explorer → single-instance agent opens → reads the file off disk → renders common
> fields + Markdown + a basic image strip → edit one field → atomic-save back.

Deliberately minimal: one resource shown via the **generic field editor** (not yet a rich plugin), no field toolkit
depth, no block lifecycle, no cache. It only has to prove the spine: **file-association → single-instance forward → read
→ render → edit → atomic-write.** Keep this code.

Touches, thinly: [[nodes#single-instance]] (single-instance/association), [[data-model#write-integrity]] (atomic write),
[[nodes#local-vs-swarm]] (local-file mode), [[plugins#fallback-editor]] (generic editor), [[plugins#tutorial-plugin]]
(Markdown + image strip).

### A2–An — Thicken the spine (iterations, each shippable)

- **A2 — Field toolkit.** Real field widgets (text, switch, tag-list, date, rating, duration, size, choice, path,
  image-count) with editor/viewer variants — the shared toolkit plugins compose from ([[plugins#core-vs-plugin]]); the
  toolkit and viewer/editor/both surfaces are designed in [[plugins#toolkit-surfaces]]. (TutCatalog5 has prior art here
  to draw on as a *design* reference.) In practice A2 is wider than the field widgets alone: it opened with its own
  mini-tracer — A2.0/#20, the document-dock shell + reactive view-model + text-field spine ([[plugins#dock-shell]],
  [[plugins#view-model]]) — and is broken into sub-slices A2.0–A2.8, tracked as issues on the GH `A2` milestone
  (session/close-guard persistence, the per-type field widgets, multi-source and image-selection editors,
  unknown-field fallback).
- **A3 — `.rehu` format + versioning.** JSON read/write, per-file format-version field, preserve-unknown-fields rule
  ([[data-model#schema-version]]). Bring `.tc`→`.rehu` migration in as the oldest *source* format
  ([[acquisition-tooling#tc-to-rehu]]) — opening a `.tc` offers migration + screenshot-name normalization. (It is not
  "format v0": a `.tc` is a different file format, not an old `.rehu`, and the mapping emits the current `.rehu` layout
  stamp included — v0 means an unstamped `.rehu`, [[data-model#schema-version]].)
- **A4 — Plugin block model.** Keyed per-plugin blocks, single-active-type rule, the save-persistence invariant (active
  type or never-claimed foreign payload; claim-then-abandon drops on save), generic fallback for inactive/unknown blocks with
  carry/map/drop ([[plugins#plugin-blocks]]/[[plugins#fallback-editor]]). This is the genuinely new core logic.
- **A5 — Tutorial plugin (rich).** Real tutorial viewer/editor: full image lightbox (click-to-maximize, prev/next,
  hideable strip, ESC), folder-rename-from-suggestions ([[plugins#tutorial-plugin]]).
- **A6 — Reference-images plugin (basic).** Type + fields + viewer; defer redaction/slideshow/search to later (they're
  [[plugins#refimages-plugin]] richness, not needed for "view/edit").
- **A7 — Log dock, task queue, checksums.** Three items, in dependency order — each is the one before it
  made useful:
  1. **In-app log viewer** — a log dock fed by a caching `logging.Handler` bridge (records logged before
     the GUI exists are replayed, not lost) plus a level-filterable log widget. rehuco has only colorized
     console logging today, while every recent predecessor shipped this; prior art, including the
     cache-then-replay design, is in [[pyside-ibo#log-stack]]. **First** — it is the simplest real dock,
     and it is what makes the two items below observable when they misbehave.
  2. **Task queue / dock** ([[architecture-design#components]]) — the visible, app-wide queue of slow
     operations (checksum, sync, scans, copies, node-notify, safe moves) with pause/resume/cancel/reorder,
     multi-select serializing work rather than running it all at once. Specified as a component since the
     architecture doc but never scheduled; A7 is where it lands, because checksums are its first real
     client and every later milestone (B scans, C sync/copies) assumes it exists.
  3. **Checksums** — generate/verify with algorithm-tagging, as task-queue jobs ([[data-model#checksums]])
     — pairs naturally with migration.
- **A8 — Tray + polish.** Close-to-tray/explicit-quit ([[nodes#single-instance]]), preferences.

**Exit criteria:** open any tutorial or ref-image `.rehu` (or migrate a `.tc`), view it richly, edit and atomic-save,
generate/verify checksums. Standalone, no infrastructure.

**Rough size:** ~3–5 focused dev-weeks (front-loaded refactoring against prior-version design knowledge, not
greenfield).

---

## Milestone B — Watch a tutorial from a tablet/local browser

**Goal:** from the iPad (thin browser client, [[borrowing#vacation-topology]]), browse tutorials a node serves and watch
one, with progress recorded. Single node, on the LAN — **no swarm, no pairing, no multi-node sync, no auth-propagation**
(single-node base case, [[multiplicity#single-node-base]]).

> Note: this introduces the **node** and the **agent-as-node-client** refactor ([[nodes#two-roles]]) — the first
> architecturally new spine beyond Milestone A.

### B1 — Tracer bullet (the spine)

> A single headless node serves an HTTP page listing one configured tutorial → tap it → browser plays the video →
> progress is recorded server-side and survives a reload.

Minimal: one node, one hard-configured folder, no catalog DB yet (or the simplest possible), no auth, plain video
serving. Proves the spine: **node serves → browser lists → browser plays → progress persists.**

Touches, thinly: [[nodes#overview]] (REST node), [[multiplicity#single-node-base]] (single-node), web stack
(FastAPI/HTMX/Pico — new skill), [[plugins#tutorial-plugin]] web/follow, progress write
([[sync#overview]]/[[mounts-and-storage#node-handoff]] minimal).

### B2–Bn — Thicken

- **B2 — Agent-as-node-client refactor.** Move the agent's catalog reads to go through a node ([[nodes#two-roles]]). The
  local-file viewer (Milestone A) stays node-free; only catalog/swarm operations route through the node. (`rehuco-node`
  package created now.)
- **B3 — SQLite cache + incremental scan.** The node builds `.rehudb` from `.rehu` files, version-aware incremental scan
  ([[data-model#scan-and-staleness]], [[data-model#local-file-trio]]).
- **B4 — Generic + tutorial browsers.** Table view with common columns + tutorial columns (duration, progress); click
  opens viewer; click-to-filter on tag/author/publisher ([[plugins#browsers]]). (Desktop first; web browser view can
  mirror it.)
- **B5 — Web follow mode.** Sequential playback, progress/duration tracking, notes, bookmarks in the browser
  ([[plugins#tutorial-plugin]] web).
- **B6 — Progress sync frequency + handoff basics.** Frequent progress writes so a reload/resume is current
  ([[mounts-and-storage#node-handoff]]) — even single-node benefits.
- **B7 — Minimal auth (optional this milestone).** Even single-user, a login gate for the web UI
  ([[discovery-trust-access#user-auth]]) if you want the tablet to require it; can defer if it's just you on a trusted
  LAN.

**Exit criteria:** open the web UI on the iPad over the LAN, see your tutorials, watch one, progress is remembered
across sessions and devices.

**Rough size:** ~4–6 focused dev-weeks, much of it the web-stack learning curve (new to you) rather than architecture.
The node runs on a capable box (Mac mini or always-on Linux node); the TS-230 is accessed via its existing SMB share
([[packaging-deployment#ts230-as-nas]]).

---

## Milestone C — Borrow a local copy for offline viewing

**Goal:** before leaving, borrow a tutorial onto a laptop; watch it offline (the laptop runs its own node,
[[borrowing#vacation-topology]]); sync progress/notes back on return. This is a **two-party** sync (home node ↔ laptop),
far simpler than general swarm sync.

### C1 — Tracer bullet (the spine)

> Mark a tutorial "borrow" → its files + `.rehu` copy onto the laptop, borrow recorded in the user meta block
> ([[borrowing#recording-borrows]]) → laptop node serves it offline → on return, progress/notes reconcile back.

Touches, thinly: [[borrowing#another-instance-role]] (borrow as instance role),
[[instances-and-dedup#instance-registry]] (instance tracking),
[[sync#overview]]/[[offline-editing#overview]] (two-party reconcile), [[borrowing#recording-borrows]] (borrow-in-meta).

### C2–Cn — Thicken

- **C2 — Instance registry (minimal).** Track where a UUID's copies live + roles; enough for borrow/return
  ([[instances-and-dedup#instance-registry]]).
- **C3 — Version-vector + activity-log sync.** The real reconcile machinery ([[sync#overview]]), scoped to two parties
  first.
- **C4 — Return/reconcile UI.** Merge progress/notes; handle the borrow-vs-changed cases
  ([[borrowing#borrow-vs-delete]]) if they arise.
- **C5 — Scheduled archival.** Borrow→archive-on-return, full or selective ([[borrowing#scheduled-archival]]).

**Exit criteria:** borrow → go offline → watch + take notes → return → changes reconciled.

**Rough size:** ~3–5 focused dev-weeks in the minimal (laptop + one home node) topology.

---

## What is deliberately deferred past these three

Everything that isn't on the personal critical path, per the architecture doc's own scoping:

- **Full swarm** (multi-node discovery, pairing, registry chatter, fingerprint mapping, benchmarking, safe-move) —
  [[discovery-trust-access]], [[mounts-and-storage#fingerprint-map]]–[[mounts-and-storage#safe-move-rename]].
  Defer until single-node + borrow is serving
  you daily; you may want it
  less than expected.
- **Acquisition tooling** (LLM URL extraction, image-drag, HTML→Markdown) — [[acquisition-tooling#overview]]. Explicitly
  deferred until after the tutorial web viewer; manual entry suffices meanwhile. (HTML→Markdown and image-drag are cheap
  enough to slip into Milestone A if convenient.)
- **Reference-image richness** (redaction, tag/semantic search, sketch slideshow, drawing critique) —
  [[plugins#refimages-plugin]].
- **Daz3D, 3D objects, dedup review UI, access-control grammar, multi-user auth propagation, web for non-tutorial
  types.**
- **Native end-user installers + auto-update** — Briefcase-built installers with declarative file association / icon /
  AUMID, MSIX later, and self-update against a public release oracle
  ([[packaging-deployment#app-identity]]/[[packaging-deployment#auto-update]]). `uv tool install` covers the author's
  own machines until then; the file-association *mechanics* are proven earlier by the Pre-work spike, but
  packaging-for-distribution and update delivery (incl. code-signing/notarization) wait.

## Sequencing gates (decide-before-you-start)

- **Before A2:** enough of the tutorial + ref-image field lists to render them (the generic editor needs nothing).
- **Before the dock manager + mixed QML/QWidgets UI is adopted:** the pyqtads + QML integration *spike*
  (pre-work, issue #4) — confirms a QML dock detaches/re-docks and coexists with QWidgets docks on current
  versions. Done; the dock-manager half is already adopted — the QtAds document-dock shell landed with
  the A2.0 tracer (#20, [[plugins#dock-shell]]) — while the first QML dock is still ahead.
- **Before A1 relies on "double-click → opens":** the file-association + app-identity *spike* (pre-work) — macOS
  `.app`/`QFileOpenEvent` and Windows ProgID/AUMID, so default-double-click open and taskbar pin/running actually work;
  also settles Briefcase as the end-user packager.
- **Before B (serving NAS content):** no glibc gate — the node runs on capable hardware with the TS-230 mounted via SMB
  ([[packaging-deployment#ts230-as-nas]]). The glibc canary findings ([[packaging-deployment#glibc-canary]]) are kept as
  a reference if direct QNAP deployment is ever reconsidered.
- **Before B web work:** a short FastAPI/HTMX/Pico **spike**, since it's a new stack — answer "can I build the
  follow-mode page the way I need?", keep the lesson, discard the toy.
- **Before B1 promises "browser plays the video":** an iPad-playback **spike** — serve a representative sample of the
  real catalog to the actual tablet: container/codec coverage (Safari plays H.264/HEVC in MP4/MOV; MKV — common in
  tutorial catalogs — does not play natively), the self-signed-HTTPS trust story
  ([[appendices.open-questions#still-open]]), and HTTP Range seeking. The outcome decides whether Milestone B grows a
  remux/transcode task-queue job.
- **Before C:** nothing new architecturally — it reuses [[sync#overview]]'s reconcile, scoped to two parties.

## Honest caveats

- Estimates are *focused dev-weeks* (uninterrupted equivalent), not calendar time, and assume the design holds under
  implementation — building always surfaces changes (as the design conversation itself repeatedly showed). Treat them as
  ordering and relative-size guidance, not promises.
- The prior versions de-risk **design** (you know what you want, you've tried approaches) more than they supply
  **droppable code** — especially since only the oldest (TutCatalog4, C++/Qt5) reached "usable," and the Python ones are
  ideas/scaffolding to redesign.
- Personal-priority path (Milestones A+B) to a genuinely useful tool: **~7–11 focused dev-weeks**, with a
  *standalone-usable* result already at the end of Milestone A.
