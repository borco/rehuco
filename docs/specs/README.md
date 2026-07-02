# rehuco — Design Specs

This directory holds the rehuco design. It is split into topic files, each owning a
contiguous range of globally-numbered sections (`§N`). The high-level overview is in
[architecture-design.md](architecture-design.md); everything else hangs off the numbers
below.

## Document map

To resolve any `§N` reference, find its number here — this table is the single source of
truth for what a section number means and which file it lives in.

| § | Section | File |
| --- | --- | --- |
| 1–3 | Problem statement · why distributed · components | [architecture-design.md](architecture-design.md) |
| 4 | Data Model | [data-model.md](data-model.md) |
| 5 | Node Communication | [nodes.md](nodes.md) |
| 6 | Discovery, Swarm Identity, and Trust | [discovery-trust-access.md](discovery-trust-access.md) |
| 7 | Sync & Conflict Resolution | [sync.md](sync.md) |
| 8 | Multiplicity: Swarms and Nodes per Machine | [multiplicity.md](multiplicity.md) |
| 9 | Mounts, `.rehuco`, and Cross-Box Visibility | [mounts-and-storage.md](mounts-and-storage.md) |
| 10 | Identity, Instance Tracking, and Deduplication | [instances-and-dedup.md](instances-and-dedup.md) |
| 11 | Borrowing, Library-Shelf Storage, and Scheduled Archival | [borrowing.md](borrowing.md) |
| 12 | Offline Editing Without a Deliberate Checkout | [offline-editing.md](offline-editing.md) |
| 13 | Plugins | [plugins.md](plugins.md) |
| 14 | Functional Requirements Carried Into the Architecture | [requirements.md](requirements.md) |
| 15 | Acquisition and Migration Tooling | [acquisition-tooling.md](acquisition-tooling.md) |
| 16 | Code Organization, Packaging, and Deployment | [packaging-deployment.md](packaging-deployment.md) |
| 17 | Field Schema (v1, `.tc`-compatible) | [field-schema.md](field-schema.md) |
| A01 | Briefcase Packaging — Native Builds, File Association, App Identity | [appendices/briefcase-packaging.md](appendices/briefcase-packaging.md) |
| A02 | Open Questions — Out of Scope and Not Yet Designed | [appendices/open-questions.md](appendices/open-questions.md) |
| A03 | Testing and Cross-Platform QA | [appendices/testing.md](appendices/testing.md) |
| A04 | Windows Dev Launcher — Hurdles and Solutions | [appendices/windows-dev-launcher.md](appendices/windows-dev-launcher.md) |

The milestone breakdown and build sequencing live separately in
[implementation-plan.md](implementation-plan.md).

## Reading order

- **First pass:** [architecture-design.md](architecture-design.md) (§1–§3) for the problem
  and the shape of the solution.
- **Core data and protocol:** §4 data model → §5 node communication → §6 discovery/trust →
  §7 sync.
- **Storage and identity:** §9 mounts → §10 instances/dedup → §11–§12 borrowing/offline.
- **Extensibility and delivery:** §13 plugins → §14 requirements → §15 tooling →
  §16 packaging → §17 field schema.
- **Appendix (alphabetical, after all `§N`):** §A01 Briefcase packaging, §A02 open questions /
  out of scope, §A03 testing & cross-platform QA, §A04 Windows dev-launcher lessons — stored under
  [appendices/](https://github.com/borco/rehuco/tree/master/docs/specs/appendices).

## Section-numbering convention

- **Numbers are global across the whole spec set.** A bare `§N` (or `§N.M`) is unambiguous
  project-wide and resolves via the document map above. Every section heading carries its
  number (`## §7. Sync & Conflict Resolution`).
- **This table is authoritative.** It is the one place that maps a number to a title and a
  file. Keep it in sync when sections are added, moved, or retired.
- **Renumber-and-shift on insert — no letter suffixes.** To insert between `§9.5` and
  `§9.6`, make the new one `§9.6` and shift the old `§9.6 → §9.7`, updating every reference
  in the same change. Do not use suffixes like `§9.5a`. Numbers are addresses, not history;
  they are allowed to change, and references move with them.
- **Don't reuse a retired number** for something unrelated — that reintroduces the very
  ambiguity the global scheme exists to prevent.
- **Appendices are numbered `§A01`, `§A02`, … (`A` for appendix)** and live under
  `appendices/`, after all the numbered `§N` topic files regardless of how high `N` climbs. They
  are **ordered alphabetically by title**, and each title's first word shares its first letter
  with its filename (e.g. `§A01` *Briefcase Packaging* ↔ `briefcase-packaging.md`). Inserting one
  therefore **renumber-and-shifts** the rest, updating every `§A0N` reference in the same change —
  the same rule as `§N` above. Appendix subsections are `§A01.1`, `§A01.2`, … and are referenced
  like any other (`§A01.2`).
