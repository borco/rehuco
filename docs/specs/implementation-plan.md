# rehuco — Implementation Plan (Tracer-Bullet First Slices)

Companion to `architecture-design.md`. This plan covers the **near-term build** scoped to the stated personal priorities:

1. View/edit local `.rehu` for basic tutorials and reference images.
2. Watch a tutorial from a tablet/local browser.
3. (later) Borrow a local copy for offline viewing on leave.

## Before you create the monorepo (one-time, cheap-now/costly-later)

These are settled; listed so nothing is forgotten at `uv init`:

- **Name: `rehuco`** (decided). It propagates into package names (`rehuco-core`, `rehuco-node`, `rehuco-agent`), PyPI namespace, import paths, file extensions (`.rehu`/`.rehuco`/`.rehudb`/`.rehusw`), config dirs, and the swarm-ID scheme — which is exactly why it's chosen before init.
- **Reserve PyPI names** via throwaway `0.0.0` stub repos (the same move used for `pyside6-scintilla`/`-lexilla`): claim `rehuco`, `rehuco-core`, `rehuco-node`, `rehuco-agent` before anyone squats them.
- **Root `pyproject.toml` is a *virtual* workspace** — no `[project]` table, only `[tool.uv.workspace]` (§16.2). Decided.
- **`rehuco-node` gets a low `requires-python` floor** matching the TS-230's Python, set at creation so the workspace intersection (§16.4) never locks the node out of the QNAP. Confirm against what the QNAP actually runs.
- **Fresh git history** — start clean, old repos kept read-only as archive (§16.6). Decided.

## Methodology: agile cadence, tracer-bullet spines

**Agile** and **tracer bullets** are not alternatives — agile is the *cadence* (short iterations, something usable each cycle, adjust as you learn), tracer bullets are a *technical strategy* used within it (build a thin, real, kept end-to-end skeleton through every layer first, then thicken). This plan uses **agile iterations whose first slice of each milestone is a tracer bullet.**

Why tracer bullets specifically fit here:

- The risk is **integration, not features** — the architecture doc shows the features are understood; what's unproven is that the layers *connect* (agent↔node client split, the field/block model rendering end-to-end). **UI approach: both QML and QtWidgets**, each where it's strongest — QWidgets (with pyqtads docking) for dense sortable/filterable tables and trees (the browsers, §13.1c) and the app shell; QML for the image grid and animated lightbox. This needs the pyqtads-hosts-QML integration to hold (the spike below). Note: the "NVIDIA overlay" prompt seen on app start is the GeForce/NVIDIA App **in-game overlay** reacting to the GPU context — a per-machine NVIDIA-software setting to toggle off, *not* an app concern and not a rendering problem; it imposes no architectural constraint.
- It **counters the prior failure mode** — earlier versions built layers deeply (a full field/type system in TutCatalog5) without reaching a usable end-to-end whole. A tracer bullet keeps a usable-if-minimal thing alive from iteration one.
- Tracer bullets are **kept production code**, not throwaway prototypes — exactly the discipline wanted after three discarded attempts.

**Rule for every milestone:** the first iteration is the thinnest end-to-end path that *works and is kept*. Later iterations thicken one part without breaking the working spine.

### Spikes vs. tracer bullets (a related but different distinction)

A third term, **spike** (from XP), is often confused with a tracer bullet. They're distinguished by **what you keep**, which follows from **what question each answers**:

- **Spike** — answers *"I don't know how/whether X works — let me find out."* Time-boxed, quick-and-dirty, **throwaway by intent.** Its product is *knowledge*; the code is deleted afterward (keep the lesson, not the toy).
- **Tracer bullet** — answers *"do my layers connect end-to-end?"* Minimal but **real, production-grade, and kept.** Its product is a *working skeleton* you build on.
- **Prototype** — like a spike (throwaway), but broader/UX-exploratory rather than one sharp technical question.

**The trap:** letting a spike quietly become load-bearing — building on quick-and-dirty exploration code written *before* you understood the problem. Decide up front which you're writing and honor it. Quick test: *"if this works, do I keep the code or just the lesson?"* Keep the code → tracer bullet (write it properly). Keep the lesson → spike (write it fast and **delete it**).

**They sequence:** for a layer with genuine unknowns → **spike** (learn, discard) → **tracer bullet** (build the thin real spine, now informed) → **thicken** (iterations). Skip the spike where there are no real unknowns.

In this plan, **A0/B0/C0 are tracer bullets** (kept spines). The items flagged *(spike)* below are throwaway — keep the lesson, delete the code.

### Model strategy (Claude Code): `opusplan` backbone, manual escalation for the hard cores

> [!NOTE]
> **Use `opusplan` as the default** (set `/model opusplan` at the start of each session). It ties model choice to mode: **Opus in plan mode** (architecture, edge cases, tradeoffs), then **automatically switches to Sonnet in execution mode** for code generation. For ~90% of rehuco — field widgets, UI wiring, REST endpoints, web templates, migration tooling — this gives Opus-quality planning and Sonnet-speed execution with no micromanagement, and it's *better* than hand-switching for routine work.
>
> **Its one blind spot matters for this app:** `opusplan` switches on *mode*, not on *how hard the code is*. It assumes "execution = mechanical." But rehuco has a few cores where the *implementation itself* is reasoning-dense and a subtle error silently corrupts data. For those, **manually switch to Opus (`/model opus`) even while implementing** — context carries over, so you can drop back to `opusplan`/Sonnet after. These cores are marked with `> [!NOTE]` blocks in `architecture-design.md`; they are:
> - **Sync engine** — version vector + activity log, conflict/merge, tombstones (§7).
> - **Plugin block save invariant** — the live/inert/claim-then-abandon rule (§13.1a).
> - **Registry resolution & serve-after-resync** — preferred-authority/chatter, version-marker comparison (§6.6, §6.10).
> - **Cross-filesystem safe move** — checksum-gated, data-loss-sensitive (§9.12).
>
> Don't micro-manage beyond that — constant hand-switching for ordinary work wastes effort; the point of `opusplan` is to handle the common case so attention goes only to these few exceptions. Feeding the relevant `§` section into context makes even Sonnet reliable on the routine parts and Opus more reliable on the hard ones. (Model names/aliases shift over time and by plan/provider — verify the current `/model` list in Claude Code; the *strategy* is stable regardless of version numbers.)

---

## Pre-work (do before/around the first slice)

These unblock or de-risk everything after; small but high-leverage.

| Task | Kind | Why now | Notes |
|---|---|---|---|
| Stand up the monorepo (uv workspaces) | setup (kept) | The dev environment for everything; fixes the venv-confusion immediately (§16) | Root virtual workspace + `packages/rehuco-core`, `apps/rehuco-agent`; add `rehuco-node` later when Milestone B starts |
| Decide the **tutorial** and **reference-image** field lists | decision | Specific-field rendering is the one thing blocked on schema (§17.2) | The generic editor does *not* need this; only the rich per-type view does. Decide enough to start, refine later |
| Decide access-rule grammar | decision | Not needed for Milestones A/B (single user, local) | Can defer to Milestone C-ish; noted so it's not forgotten |
| **pyqtads + QML integration (regression check)** | **spike** | Confirms the "both QML and QtWidgets" approach still holds on current Qt/PySide6/pyqtads versions | QML-in-pyqtads already worked previously; this re-verifies it on current versions, focused on the parts the app will depend on: a QQuickWidget dock that **detaches to a floating window and re-docks** without glitches (the classic QML cross-window trouble spot), a **QWidgets dock and QML dock coexisting** in one layout, and **layout save/restore** with a QML dock present — including **whether closed/hidden docks restore their size** (a known soft spot across all Qt docking; likely needs stashing dock size on close keyed by object name and restoring on show, rather than relying solely on the layout blob). Keep a tiny reference snippet of the working wiring; discard the rest. If a QML dock's detach glitches, the response is to **keep QML surfaces in non-detachable docks or reduce the QML footprint** — *not* switch to KDDockWidgets, which is foreclosed by its GPL license (architecture §16.7). pyqtads stays (LGPL, prebuilt PySide6 bindings) |
| **QNAP/glibc dependency canary** | **spike** | De-risks Milestone B's node deps early | Build a glibc-2.23 container; confirm FastAPI/uvicorn/zeroconf/pydantic-core/cryptography wheels load. Keep the lesson (a pinned compatible-versions list); the container/script is throwaway |
| **File association + app identity** | **spike** | De-risks A0's "double-click → opens" before A0 depends on it (§16.8) | macOS: a minimal `.app` (built via Briefcase) that's the default opener for `.rehu` and delivers the path as a **`QFileOpenEvent`** into a single running PySide6 instance (§5.4) — macOS does *not* pass it as `argv`. Windows: an HKCU **ProgID** for default double-click + an explicit **AUMID** (`SetCurrentProcessExplicitAppUserModelID`) so a pinned taskbar button shows the app's icon and lights up as running (the gap `resource-hub` only papered over with a PyInstaller exe), with `DefaultIcon` from a shipped `.ico`. Second double-click routes to the existing instance, not a new process. Keep the bundle/ProgID recipe + AUMID line; discard the toy GUI. Confirms Briefcase as the end-user packager as a side effect |

---

## Milestone A — Local view/edit (no node, no swarm, no login)

**Goal:** a standalone, usable tool that opens, displays, and edits a local `.rehu` for tutorials and reference images. This is the agent's local-file mode (§5.3), and a genuinely useful product on its own.

### A0 — Tracer bullet (the spine)

> Double-click a `.rehu` in File Explorer → single-instance agent opens → reads the file off disk → renders common fields + Markdown + a basic image strip → edit one field → atomic-save back.

Deliberately minimal: one resource shown via the **generic field editor** (not yet a rich plugin), no field toolkit depth, no block lifecycle, no cache. It only has to prove the spine: **file-association → single-instance forward → read → render → edit → atomic-write.** Keep this code.

Touches, thinly: §5.4 (single-instance/association), §4.9 (atomic write), §5.3 (local-file mode), §13.1b (generic editor), §13.2 (Markdown + image strip).

### A1–An — Thicken the spine (iterations, each shippable)

- **A1 — Field toolkit.** Real field widgets (text, switch, tag-list, date, rating, duration, size, choice, path, image-count) with editor/viewer variants — the shared toolkit plugins compose from (§13.1). (TutCatalog5 has prior art here to draw on as a *design* reference.)
- **A2 — `.rehu` format + versioning.** JSON read/write, per-file format-version field, preserve-unknown-fields rule (§4.10). Bring `.tc`→`.rehu` migration in as "format v0" (§15.3) — opening a `.tc` offers migration + screenshot-name normalization.
- **A3 — Plugin block model.** Keyed per-plugin blocks, single-live-type rule, the save-persistence invariant (live type or never-claimed foreign payload; claim-then-abandon drops on save), generic fallback for inert/unknown blocks with carry/map/drop (§13.1a/§13.1b). This is the genuinely new core logic.
- **A4 — Tutorial plugin (rich).** Real tutorial viewer/editor: full image lightbox (click-to-maximize, prev/next, hideable strip, ESC), folder-rename-from-suggestions (§13.2).
- **A5 — Reference-images plugin (basic).** Type + fields + viewer; defer redaction/slideshow/search to later (they're §13.3 richness, not needed for "view/edit").
- **A6 — Checksums.** Generate/verify with algorithm-tagging, as task-queue jobs (§4.5) — pairs naturally with migration.
- **A7 — Tray + polish.** Close-to-tray/explicit-quit (§5.4), preferences.

**Exit criteria:** open any tutorial or ref-image `.rehu` (or migrate a `.tc`), view it richly, edit and atomic-save, generate/verify checksums. Standalone, no infrastructure.

**Rough size:** ~3–5 focused dev-weeks (front-loaded refactoring against prior-version design knowledge, not greenfield).

---

## Milestone B — Watch a tutorial from a tablet/local browser

**Goal:** from the iPad (thin browser client, §11.5), browse tutorials a node serves and watch one, with progress recorded. Single node, on the LAN — **no swarm, no pairing, no multi-node sync, no auth-propagation** (single-node base case, §8.1).

> Note: this introduces the **node** and the **agent-as-node-client** refactor (§5.1) — the first architecturally new spine beyond Milestone A.

### B0 — Tracer bullet (the spine)

> A single headless node serves an HTTP page listing one configured tutorial → tap it → browser plays the video → progress is recorded server-side and survives a reload.

Minimal: one node, one hard-configured folder, no catalog DB yet (or the simplest possible), no auth, plain video serving. Proves the spine: **node serves → browser lists → browser plays → progress persists.**

Touches, thinly: §5 (REST node), §8.1 (single-node), web stack (FastAPI/HTMX/Pico — new skill), §13.2 web/follow, progress write (§7/§9.6 minimal).

### B1–Bn — Thicken

- **B1 — Agent-as-node-client refactor.** Move the agent's catalog reads to go through a node (§5.1). The local-file viewer (Milestone A) stays node-free; only catalog/swarm operations route through the node. (`rehuco-node` package created now.)
- **B2 — SQLite cache + incremental scan.** The node builds `.rehudb` from `.rehu` files, version-aware incremental scan (§4.7, §4.8).
- **B3 — Generic + tutorial browsers.** Table view with common columns + tutorial columns (duration, progress); click opens viewer; click-to-filter on tag/author/publisher (§13.1c). (Desktop first; web browser view can mirror it.)
- **B4 — Web follow mode.** Sequential playback, progress/duration tracking, notes, bookmarks in the browser (§13.2 web).
- **B5 — Progress sync frequency + handoff basics.** Frequent progress writes so a reload/resume is current (§9.6) — even single-node benefits.
- **B6 — Minimal auth (optional this milestone).** Even single-user, a login gate for the web UI (§6.7) if you want the tablet to require it; can defer if it's just you on a trusted LAN.

**Exit criteria:** open the web UI on the iPad over the LAN, see your tutorials, watch one, progress is remembered across sessions and devices.

**Rough size:** ~4–6 focused dev-weeks, much of it the web-stack learning curve (new to you) rather than architecture. Do the QNAP/glibc canary (pre-work) before relying on the QNAP as the serving node; until then serve from a capable box (the always-on Linux node or Mac mini).

---

## Milestone C — Borrow a local copy for offline viewing

**Goal:** before leaving, borrow a tutorial onto a laptop; watch it offline (the laptop runs its own node, §11.5); sync progress/notes back on return. This is a **two-party** sync (home node ↔ laptop), far simpler than general swarm sync.

### C0 — Tracer bullet (the spine)

> Mark a tutorial "borrow" → its files + `.rehu` copy onto the laptop, borrow recorded in the user meta block (§11.4) → laptop node serves it offline → on return, progress/notes reconcile back.

Touches, thinly: §11 (borrow as instance role), §10.2 (instance tracking), §7/§12 (two-party reconcile), §11.4 (borrow-in-meta).

### C1–Cn — Thicken

- **C1 — Instance registry (minimal).** Track where a UUID's copies live + roles; enough for borrow/return (§10.2).
- **C2 — Version-vector + activity-log sync.** The real reconcile machinery (§7), scoped to two parties first.
- **C3 — Return/reconcile UI.** Merge progress/notes; handle the borrow-vs-changed cases (§11.6) if they arise.
- **C4 — Scheduled archival.** Borrow→archive-on-return, full or selective (§11.3).

**Exit criteria:** borrow → go offline → watch + take notes → return → changes reconciled.

**Rough size:** ~3–5 focused dev-weeks in the minimal (laptop + one home node) topology.

---

## What is deliberately deferred past these three

Everything that isn't on the personal critical path, per the architecture doc's own scoping:

- **Full swarm** (multi-node discovery, pairing, registry chatter, fingerprint mapping, benchmarking, safe-move) — §6, §9.9–9.12. Defer until single-node + borrow is serving you daily; you may want it less than expected.
- **Acquisition tooling** (LLM URL extraction, image-drag, HTML→Markdown) — §15. Explicitly deferred until after the tutorial web viewer; manual entry suffices meanwhile. (HTML→Markdown and image-drag are cheap enough to slip into Milestone A if convenient.)
- **Reference-image richness** (redaction, tag/semantic search, sketch slideshow, drawing critique) — §13.3.
- **Daz3D, 3D objects, dedup review UI, access-control grammar, multi-user auth propagation, web for non-tutorial types.**
- **Native end-user installers + auto-update** — Briefcase-built installers with declarative file association / icon / AUMID, MSIX later, and self-update against a public release oracle (§16.8/§16.9). `uv tool install` covers the author's own machines until then; the file-association *mechanics* are proven earlier by the Pre-work spike, but packaging-for-distribution and update delivery (incl. code-signing/notarization) wait.

## Sequencing gates (decide-before-you-start)

- **Before A1:** enough of the tutorial + ref-image field lists to render them (the generic editor needs nothing).
- **Before A0 commits to the mixed QML/QWidgets UI:** the pyqtads + QML integration *spike* (pre-work) — confirms a QML dock detaches/re-docks and coexists with QWidgets docks on current versions.
- **Before A0 relies on "double-click → opens":** the file-association + app-identity *spike* (pre-work) — macOS `.app`/`QFileOpenEvent` and Windows ProgID/AUMID, so default-double-click open and taskbar pin/running actually work; also settles Briefcase as the end-user packager.
- **Before B (serving from QNAP):** the glibc dependency *spike* (pre-work).
- **Before B web work:** a short FastAPI/HTMX/Pico **spike**, since it's a new stack — answer "can I build the follow-mode page the way I need?", keep the lesson, discard the toy.
- **Before C:** nothing new architecturally — it reuses §7's reconcile, scoped to two parties.

## Honest caveats

- Estimates are *focused dev-weeks* (uninterrupted equivalent), not calendar time, and assume the design holds under implementation — building always surfaces changes (as the design conversation itself repeatedly showed). Treat them as ordering and relative-size guidance, not promises.
- The prior versions de-risk **design** (you know what you want, you've tried approaches) more than they supply **droppable code** — especially since only the oldest (TutCatalog4, C++/Qt5) reached "usable," and the Python ones are ideas/scaffolding to redesign.
- Personal-priority path (Milestones A+B) to a genuinely useful tool: **~7–11 focused dev-weeks**, with a *standalone-usable* result already at the end of Milestone A.
