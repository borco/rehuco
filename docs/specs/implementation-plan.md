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

1. View/edit local `.rehu` for tutorials and reference images — **done** (`rehuco-agent` 0.1.0–0.2.0).
2. Scan folders into a cached catalog and search it — close to the original tutcatalog — **not started**.
3. Watch a tutorial from a tablet/local browser — **superseded**: the work queue now builds an in-app
   player first (see "Tutorials — direction revised" below); the node/web approach is further out, not
   dropped.
4. (later) Borrow a local copy for offline viewing on leave — **not started**.

## Methodology: agile cadence, tracer-bullet spines

[[[implementation-plan#methodology]]]

**Agile** and **tracer bullets** are not alternatives — agile is the *cadence* (short iterations, something
usable each cycle, adjust as you learn), tracer bullets are a *technical strategy* used within it (build a
thin, real, kept end-to-end skeleton through every layer first, then thicken). This plan uses **agile
iterations whose first slice of each feature area is a tracer bullet.**

Why tracer bullets specifically fit here:

- The risk is **integration, not features** — the architecture doc shows the features are understood;
  what's unproven is that the layers *connect* (agent↔node client split, the field/block model rendering
  end-to-end). **UI approach: both QML and QtWidgets**, each where it's strongest — QWidgets (with QtAds
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
the live record of what's actually being built, and this plan catches up after the fact.

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
unknowns. Each feature area below opens with a kept tracer bullet; items flagged *(spike)* are throwaway —
keep the lesson, delete the code.

### Model strategy (Claude Code): `opusplan` backbone, manual escalation for the hard cores

[[[implementation-plan#model-strategy]]]

> [!NOTE]
> **Use `opusplan` as the default** (set `/model opusplan` at the start of each session). It ties model
> choice to mode: **Opus in plan mode** (architecture, edge cases, tradeoffs), then **automatically switches
> to Sonnet in execution mode** for code generation. For ~90% of rehuco — field widgets, UI wiring, REST
> endpoints, web templates, migration tooling — this gives Opus-quality planning and Sonnet-speed execution
> with no micromanagement, and it's *better* than hand-switching for routine work.
>
> **Its one blind spot matters for this app:** `opusplan` switches on *mode*, not on *how hard the code is*.
> It assumes "execution = mechanical." But rehuco has a few cores where the *implementation itself* is
> reasoning-dense and a subtle error silently corrupts data. For those, **manually switch to Opus (`/model
> opus`) even while implementing** — context carries over, so you can drop back to `opusplan`/Sonnet after.
> These cores are marked with `> [!NOTE]` blocks in `architecture-design.md`; they are:
>
> - **Sync engine** — version vector + activity log, conflict/merge, tombstones ([[sync#overview]]).
> - **Plugin block save invariant** — the active/inactive/claim-then-abandon rule
>   ([[plugins#plugin-blocks]]).
> - **Registry resolution & serve-after-resync** — preferred-authority/chatter, version-marker comparison
> ([[discovery-trust-access#registry-home]], [[discovery-trust-access#serve-after-resync]]).
> - **Cross-filesystem safe move** — checksum-gated, data-loss-sensitive ([[mounts-and-storage#safe-move-rename]]).
>
> Don't micro-manage beyond that — constant hand-switching for ordinary work wastes effort; the point of
> `opusplan` is to handle the common case so attention goes only to these few exceptions. Feeding the
> relevant `§` section into context makes even Sonnet reliable on the routine parts and Opus more reliable
> on the hard ones. (Model names/aliases shift over time and by plan/provider — verify the current `/model`
> list in Claude Code; the *strategy* is stable regardless of version numbers.)

---

## Local edit — remaining work

The editor is built (`packages/rehuco-agent/CHANGELOG.md`). What's left is filed: shortcut customization
(app-wide routing, #345; the command registry and the Shortcuts settings page are built) and improved dark/light
theming (#285). See those issues for the actual scope; this is only an index.

## Web scrapping — remaining work

Scraping itself is built (`packages/rehuco-agent/CHANGELOG.md`). What's left is filed: an image picker for
a page or selection dropped on the images sub-dock (#275) and a console-only CLI companion app so
`--scrape`/`--scrape-schema` work from a packaged install (#346).

## Cache DB — not started

**Goal:** point the agent at your folders, have it scan the `.rehu` files into a `.rehudb` cache, and
browse/search the catalog on the desktop — close to the original tutcatalog. Still **one machine, no
network, no node, no login**; the cache is a rebuildable derivative of the `.rehu` files, never a source of
truth ([[data-model#local-file-trio]]).

Tracer bullet (#377): open a `.rehuco` naming the folders → the agent scans their `.rehu` files into `.rehudb` → a table lists
them → opening a row opens the resource. The live text filter comes with the browser table.

Then thicken: incremental, version-aware rescanning that only touches what changed and prunes vanished
entries ([[data-model#scan-and-staleness]]); generic and tutorial browsers with click-to-filter on
tag/author/publisher ([[plugins#browsers]]); combinable field search (type, author, publisher, tags,
rating) fast enough over a large library to feel live.

**Exit criteria:** point the agent at real folders, get a searchable catalog on the desktop, and click
through to view or edit any resource.

**Filed** (label `cache db`; the shape is [[plugins#rehuco-dock]] and [[data-model#cache-schema]]):

- core — the `.rehuco` file (#371); the versioned `.rehudb` schema and full scan (#372); incremental rescan and
  targeted updates, renames included (#373).
- shared plumbing — a header menu for column visibility (#374); one view-model per open resource shared by every
  host (#375); in-place propagation of the app's own moves and changes (#376); `DocumentWidget` split so another
  dock can host a resource's sub-docks (#380).
- the Rehuco dock — the tracer above (#377); the roots column view (#378); the browser table with its filter line
  (#379); the current resource's sub-docks (#381).
- public docs once it runs (#382).

## Tutorials — direction revised

The original design here was a single node serving thin browser clients on the LAN (the
**agent-as-node-client** refactor, [[nodes#two-roles]]) — no swarm, no pairing, no auth-propagation. That
is superseded for now: an **in-app player comes first** instead, and is already filed and in progress
(#315–#319 — watch progress, the in-app player dock, video settings, external VLC). No node exists yet, and
none is scheduled ahead of that in-app work.

The node/web approach below is unfiled and further out — kept here only as an outline, once a node exists:

**Goal:** from a tablet (thin browser client), browse the tutorials a node serves and watch one, with
progress recorded. Single node, on the LAN — no swarm, no pairing, no multi-node sync, no
auth-propagation ([[multiplicity#single-node-base]]). Cache ownership moves from the agent (Cache DB above)
to the node here.

Tracer bullet: a single headless node serves an HTTP page listing one configured tutorial → tap it → the
browser plays the video → progress is recorded server-side and survives a reload.

Then thicken: the **agent-as-node-client refactor**, moving catalog reads through the node
([[nodes#two-roles]]; `rehuco-node` gets its first real code here); the Cache DB table view mirrored for
the browser ([[plugins#browsers]]); sequential web playback with progress/duration tracking, notes and
bookmarks; frequent-enough progress writes for a reload to stay current
([[mounts-and-storage#node-handoff]]); an optional login gate for the web UI if the tablet should require
one ([[discovery-trust-access#user-auth]]).

**Exit criteria:** open the web UI on a tablet over the LAN, see the tutorials a node serves, watch one, and
have progress remembered across sessions and devices.

## Borrowing — not started

**Goal:** before leaving, borrow a tutorial onto a laptop; watch it offline (the laptop runs its own node);
sync progress/notes back on return. A **two-party** sync (home node ↔ laptop), simpler than general swarm
sync, and depends on Tutorials' node existing first.

Tracer bullet: mark a tutorial "borrow" → its files + `.rehu` copy onto the laptop, borrow recorded in the
user meta block ([[borrowing#recording-borrows]]) → the laptop's node serves it offline → on return,
progress/notes reconcile back.

Then thicken: a minimal instance registry tracking where a UUID's copies live and their roles
([[instances-and-dedup#instance-registry]]); the version-vector + activity-log reconcile machinery
([[sync#overview]]), scoped to two parties; a return/reconcile UI handling the borrow-vs-changed case if it
arises ([[borrowing#borrow-vs-delete]]); scheduled archival on return, full or selective
([[borrowing#scheduled-archival]]).

**Exit criteria:** borrow → go offline → watch and take notes → return → changes reconciled.

## Reference images — richness not started

Viewing and editing a reference-images resource is done and genuinely usable: the resource type, its
fields, checksums, and the **Content Images** dock (#221 — a grid over a pack's archive members, a
decode-on-demand lightbox) all shipped. What's unbuilt is the *richness* layer on top:
the `.rehuimg` sidecar skeleton, a `rehuco-vision` inference package, redaction (blur, per-user overrides,
a region sub-dock, the scope cascade, a cover/inpainting effect), tagging and embeddings, a Pinterest-style
in-pack and cross-pack search, and pose-driven ranking ([[reference-images]]). This is its own wave of GH
issues (category `reference images`); the current sequencing lives in the work queue and on those issues
rather than here, since it has since overtaken the slice-by-slice breakdown this page used to carry. Order
decided at filing: sidecar and vision skeleton first, then **redaction** and **search** interleave; 360°
identification and practice mode are deliberately last.

## Deferred

- **LLM URL extraction** — [[acquisition-tooling#llm-url-extract]], a fallback for hosts no scraper
  matches. Deferred until a real run of unmatched hosts says it's worth a model; a user-written scraper
  covers the gap meanwhile.
- **3D objects, a dedup review UI, an access-control grammar, multi-user auth propagation, web for
  non-tutorial types.**
- **Auto-update** — the installers themselves landed (#206,
  [[appendices.briefcase-packaging#status]]): Briefcase-built installers with declarative file
  association/icon/AUMID. MSIX packaging and self-update against a public release oracle still wait on
  code-signing/notarization ([[packaging-deployment#app-identity]]/[[packaging-deployment#auto-update]]).
- **Swarm** (full multi-node: discovery, pairing, registry, safe-move —
  [[discovery-trust-access]], [[mounts-and-storage#fingerprint-map]]–[[mounts-and-storage#safe-move-rename]])
  and **Daz3D library migration** are their own further-out efforts, out of scope for everything above.

## Sequencing gates still open

- **Before Tutorials' web/node work:** a short FastAPI/HTMX/Pico **spike**, since it's a new stack — answer
  "can the follow-mode page be built the way it's needed", keep the lesson, discard the toy.
- **Before promising "the browser plays the video" to a tablet:** an iPad-playback **spike** over a
  representative sample of the real catalog — container/codec coverage (Safari plays H.264/HEVC in MP4/MOV;
  MKV, common in these catalogs, does not play natively), the self-signed-HTTPS trust story
  ([[appendices.open-questions#still-open]]), and HTTP Range seeking. The outcome decides whether Tutorials'
  node needs a remux/transcode task-queue job.
- **Before Borrowing:** nothing new architecturally — it reuses [[sync#overview]]'s reconcile, scoped to two
  parties.

## Honest caveats

- The prior versions de-risked **design** more than they supplied droppable code — only the oldest
  (TutCatalog4, C++/Qt5) reached "usable," and the Python ones were ideas/scaffolding to redesign
  (see [project history](history/README.md)).
- Nothing above is estimated in dev-time; the size a piece of work turns out to be is tracked on its GH
  issue (`XS`–`XL` labels, [[appendices.project-management#category-labels]]) once it's actually filed.
