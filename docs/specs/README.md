# rehuco — Design Specs

[[[readme]]]

This directory holds the rehuco design, split into topic files. The high-level overview is in
[architecture-design.md](architecture-design.md). Cross-references between specs use the stable
`[[doc#slug]]` tokens defined below — see "Symbolic cross-references."

## Document map

[[[readme#document-map]]]

A quick index from `§N` number to file and reading order. Cross-references don't need it — every
doc/slug is self-resolving (see below) — but it's handy when skimming a heading number cold, or
picking a next file to read: **core data/protocol** (§4–§7) → **storage/identity** (§9–§12) →
**extensibility/delivery** (§13–§17) → **appendices** (unnumbered, alphabetical by title, after all
`§N`). The milestone breakdown lives separately in [implementation-plan.md](implementation-plan.md).

| § | Doc key | Section | File |
| --- | --- | --- | --- |
| 1–3 | `architecture-design` | Problem statement · why distributed · components | [architecture-design.md](architecture-design.md) |
| 4 | `data-model` | Data Model | [data-model.md](data-model.md) |
| 5 | `nodes` | Node Communication | [nodes.md](nodes.md) |
| 6 | `discovery-trust-access` | Discovery, Swarm Identity, and Trust | [discovery-trust-access.md](discovery-trust-access.md) |
| 7 | `sync` | Sync & Conflict Resolution | [sync.md](sync.md) |
| 8 | `multiplicity` | Multiplicity: Swarms and Nodes per Machine | [multiplicity.md](multiplicity.md) |
| 9 | `mounts-and-storage` | Mounts, `.rehuco`, and Cross-Box Visibility | [mounts-and-storage.md](mounts-and-storage.md) |
| 10 | `instances-and-dedup` | Identity, Instance Tracking, and Deduplication | [instances-and-dedup.md](instances-and-dedup.md) |
| 11 | `borrowing` | Borrowing, Library-Shelf Storage, and Scheduled Archival | [borrowing.md](borrowing.md) |
| 12 | `offline-editing` | Offline Editing Without a Deliberate Checkout | [offline-editing.md](offline-editing.md) |
| 13 | `plugins` | Plugins | [plugins.md](plugins.md) |
| 14 | `requirements` | Functional Requirements Carried Into the Architecture | [requirements.md](requirements.md) |
| 15 | `acquisition-tooling` | Acquisition and Migration Tooling | [acquisition-tooling.md](acquisition-tooling.md) |
| 16 | `packaging-deployment` | Code Organization, Packaging, and Deployment | [packaging-deployment.md](packaging-deployment.md) |
| 17 | `field-schema` | Field Schema (v1, `.tc`-compatible) | [field-schema.md](field-schema.md) |
| | **Appendices** | | |
| | `appendices.briefcase-packaging` | Briefcase Packaging — Native Builds, File Association, App Identity | [appendices/briefcase-packaging.md](appendices/briefcase-packaging.md) |
| | `appendices.code-conventions` | Code Conventions | [appendices/code-conventions.md](appendices/code-conventions.md) |
| | `appendices.continuous-integration` | Continuous Integration — Design Decisions and Hurdles | [appendices/continuous-integration.md](appendices/continuous-integration.md) |
| | `appendices.open-questions` | Open Questions — Out of Scope and Not Yet Designed | [appendices/open-questions.md](appendices/open-questions.md) |
| | `appendices.project-management` | Project Management — Issue Labels and Sizing | [appendices/project-management.md](appendices/project-management.md) |
| | `appendices.qt-ads` | QtAds — Hurdles and Solutions | [appendices/qt-ads.md](appendices/qt-ads.md) |
| | `appendices.settings-pages` | Settings Pages — Managing App-Wide Configuration | [appendices/settings-pages.md](appendices/settings-pages.md) |
| | `appendices.testing` | Testing and Cross-Platform QA | [appendices/testing.md](appendices/testing.md) |
| | `appendices.theming_and_styling` | Theming and Styling | [appendices/theming_and_styling.md](appendices/theming_and_styling.md) |
| | `appendices.windows-dev-launcher` | Windows Dev Launcher — Hurdles and Solutions | [appendices/windows-dev-launcher.md](appendices/windows-dev-launcher.md) |

**Numbering, briefly:** `§N`/`§N.M` (the core §1–§17 docs) are global and renumber-and-shift on
insert — update every heading number in the same change, and never reuse a retired number.
**Appendices carry no `§` number at all** — ordered alphabetically by title in this table (each
title's first letter matching its filename) — their own subsection headings (`## 1.`, `### 1.1`, …)
are a plain, file-local counter with no cross-file meaning; a cross-reference always uses the
`[[doc#slug]]` token, never a bare number.

> [!NOTE]
> Project history lives outside this numbering scheme: the predecessor projects that led here are
> collected under [history/](history/README.md) — a project timeline plus per-project notes.

## Symbolic cross-references

[[[readme#symbolic-cross-references]]]

Every heading carries a stable declaration on its own line right beneath it: a **triple-bracket**
token, `[[[doc#slug]]]` (dot-qualified for appendices: `[[[appendices.open-questions#still-open]]]`).
A file's own H1 gets one too, **without a slug** — `[[[doc]]]` — declaring a whole-document anchor
for references that don't belong to any one subsection. Every other occurrence of that same token —
prose in another spec, a `.py` docstring — is a **double-bracket reference**: `[[doc#slug]]` for one
heading, bare `[[doc]]` for the whole document.

- **How to use it:** to point at a specific heading, reference its declared slug —
  `[[plugins#field-toolkit]]`. To point at a whole document with no single relevant heading,
  reference the bare doc key — `[[data-model]]`. To add a new heading, declare its slug once,
  directly beneath it — `[[[field-schema#new-heading]]]` — then reference that slug everywhere else.
- **Not a clickable link — a grep convention.** Search the repo for the exact token; the
  triple-bracket form is the declaration, the double-bracket form is a reference. This deliberately
  sidesteps chasing identical clickable-anchor behavior across GitHub and the published mkdocs site,
  which isn't achievable cheaply (the two renderers handle anchors differently).
- **Styled like inline code on the published site, still not a link.** A small mkdocs hook
  (`tools/mkdocs_slug_ref_hook.py`) renders every token in a `.slug-ref`-styled `<span>` purely for
  legibility, so it doesn't read as ordinary prose; it stays inert (no click behavior) and GitHub's
  rendering is unaffected.
- **The extra bracket is structural, not cosmetic.** A reference can land alone on its own line
  purely as a byproduct of word-wrapping — with a same-bracket-count scheme that would be
  indistinguishable from a real declaration. The triple/double distinction means wrapping can never
  manufacture a false declaration.
- **Self-resolving.** The doc name is in the token itself (`plugins` in `[[plugins#field-toolkit]]`),
  so no document-map lookup is needed to find which file it's in.
- **`tools/check_slug_refs.py`** (wired into `make qa` as `check-slugs`) walks every token in
  `docs/**/*.md`, the root `CLAUDE.md`, every tracked `README.md`, and `.py` under `packages/`,
  failing on a duplicate declaration, a reference with no declaration, or a declaration whose `doc`
  doesn't match the file it's in.

## Why not just `§N.M`

[[[readme#why-not-numbers]]]

Bare numbers were the only cross-reference scheme early on, and two hurdles pushed off of them:

- **Renumber-and-shift is fine within one file, expensive across the set.** Inserting `§9.6` and
  shifting `§9.6 → §9.7` is a local, contained edit. Inserting a new **document** is not: a topic
  file landing at position 8 shifts every document after it — old `§8 → §9`, `§9 → §10`, … up
  through `§17` — and every reference to any of those chapters, in every other spec file and every
  `.py` docstring, needs updating in the same change. One insert, project-wide fan-out.
- **Whole-chapter references had nowhere to point.** A reference to a concept spanning a whole doc
  (not one heading) had only the bare number to fall back on, resolved by eye against the document
  map — with nothing checking that the number still meant the same chapter after a later renumber.
  The bare `[[[doc]]]` H1 declaration closes this: every document now has its own anchor, so nothing
  needs the fallback.

**Syntax candidates tried and rejected** before landing on `#`:

- `[[doc][slug]]` — valid CommonMark full-reference-link syntax, so markdownlint's MD052 flags every
  occurrence as an undefined reference label.
- `[[doc.slug]]` (fully dot-separated) — passes lint, but ambiguous once a dotted doc key is
  involved (`appendices.open-questions.still-open` doesn't disambiguate doc-path depth from slug).
- `[[doc/slug]]`, `[[doc|slug]]` — both pass lint. `|` risks reading as an Obsidian/MediaWiki
  wikilink's "alternate display text," not "anchor within the page"; `/` implies file-path nesting
  that isn't accurate here.
- Unicode delimiters (guillemets, etc.) — rejected outright: must be typeable on a standard keyboard.
- `#` won on all counts: passes lint, mirrors the universal URL-fragment convention
  (`page.html#anchor`), and reads correctly on sight.

**Clickable-anchor parity across GitHub and the published mkdocs site was considered and rejected**
as a goal — not achievable cheaply, since the two renderers handle anchors differently (`attr_list`
is invisible to GitHub; raw HTML anchor ids get silently prefixed there). The grep-based token
sidesteps the problem instead of solving it.
