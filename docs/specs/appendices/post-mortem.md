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
  brittle, per-site, and repeatedly broken by site changes. Deferred and slated for replacement by LLM-assisted
  URL extraction rather than revival. Detail: [[acquisition-tooling#overview]] (and the predecessor
  [histories](../history/README.md) that carried it).

## Process

[[[appendices.post-mortem#process]]]

- **Building layers deeply in isolation before a working whole.** Earlier attempts (notably TutCatalog5) built a
  full field/type system before anything worked end-to-end, and never reached a usable product. Replaced by
  **tracer-bullet-first** slices — a thin, kept, end-to-end spine per milestone, thickened afterward. Detail:
  [[implementation-plan#methodology]].
