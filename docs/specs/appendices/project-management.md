# Project Management — Issue Labels and Sizing

[[[appendices.project-management]]]

## Overview

[[[appendices.project-management#overview]]]

How work is labeled on the [issue tracker](https://github.com/borco/rehuco/issues).
Three orthogonal label families annotate every implementation issue: a **category label** (which feature
family the work belongs to), a **model label** (which agent model executes it, and in what mode) and a
**size label** (how long it is expected to take that agent). They exist so the issue list can be triaged
at a glance — pick a family, then by capability, then by available time — and so estimates stay
comparable across issues.

The model and size labels carry matching prose sections in the issue body: a `## Model` section naming
the model/mode, and a `## Estimate` section with the expected agent time. The label is the skimmable
index; the body section is the record (and can carry a one-line rationale). Keep the two in step.

## Audit runs

[[[appendices.project-management#audit-runs]]]

Maintenance is collected under the **`audit`** label — one sweep of the codebase at a time.
A run reads the code as a whole rather than following a feature, and each finding becomes an ordinary
issue carrying `audit`, sized and labeled like any other. The point of running a sweep at all is that
quality work is **periodic and bounded**: a sweep that produces 24 issues is a batch to schedule, where
the same 24 noticed one at a time are noise to be ignored.

Standing sweeps, each looking for a different kind of rot:

- **Code** — correctness against untrusted input, edge hardening, and residue left by earlier slices.
- **Docs vs. code** — where the design docs and the implementation have drifted apart.
- **Public claims vs. reality** — `README.md`, `docs/index.md`, package descriptions and READMEs, and
  the GH description and topics, against what actually runs. The rule they answer to is in `CLAUDE.md`
  ("Public-facing claims"); this sweep is what catches the pages that were written before the rule, or
  by a hand the rule doesn't reach. It is deliberately a periodic audit rather than a build-time check:
  the failure is a sentence written in the present tense too early, which no checker recognizes — and a
  checker would need its own hand-maintained table of claims and their proof, drifting exactly like the
  thing it polices.

## Category labels

[[[appendices.project-management#category-labels]]]

One category label per issue — the feature family the work belongs to, named for the milestone family
that carries it in [[implementation-plan]]. This is what GH milestones used to express; they now mark
**releases** and nothing else, so the family an issue belongs to and the release it is cut into are two
independent facts rather than one overloaded field.

| Label | Family | Meaning |
| --- | --- | --- |
| `pre-work` | Pre-work | Monorepo setup, integration spikes, de-risking. |
| `local edit` | LocalEdit | Local view/edit of resources. |
| `cache db` | CacheDB | Cached database. |
| `watch tutorial` | WatchTutorial | Watch a tutorial. |
| `borrowing` | Borrowing | Offline borrow. |
| `swarm` | Swarm | Full multi-node. |
| `daz3d` | Daz3D | daz3d-personal-database migration. |
| `web scrapping` | WebScrapping | Browser drops and site scrapers feeding the editor. |
| `reference images` | RefImages | Image tagging, search, practice. |

The table fixes each name in advance, which is its main job: a label invented at the moment the first
issue of a family is filed gets invented twice, and a near-miss (`webscraping` beside `web scrapping`)
splits a family's issue list in a way nothing catches. Every row above exists on the tracker, including
the families with no issue filed against them yet; a family added to this table later gets its label the
same way, and `gh label list` stays the live register.

Two labels stand where a category would be, and neither is one:

- **`deferred`** — filed but deliberately unplanned. It replaces the category rather than joining it,
  because assigning a family to work nobody has decided to do implies a schedule that does not exist.
  Such an issue needs a decision or a split before it can be scheduled, and picks up its category then.
- **`audit`** — a finding from a codebase sweep (above). Orthogonal, not a substitute: an audit finding
  about the editor still carries `local edit`.

## Model labels

[[[appendices.project-management#model-labels]]]

One model label per issue — an issue is written to be executed by a single model. When a piece of
work genuinely needs different models for different parts, split it into separate issues along
that seam (e.g. a core issue and an agent issue), rather than mixing models inside one issue
(see [[implementation-plan#model-strategy]] for the strategy this implements).

| Label | Meaning |
| --- | --- |
| `opusplan` | The default VSCode Claude Code mode: Opus plans, Sonnet executes. |
| `sonnet` | Sonnet end to end. |
| `opus` | Opus end to end. |
| `fable` | Fable end to end. |

How to choose:

- **`opusplan`** — the default. Work with a real but small design decision up front (an API shape,
  a routing path, a subclass-vs-helper call) followed by a mechanical implementation.
- **`sonnet`** — mechanical, well-specified work: the issue body already states the fix shape and
  the change is a contained edit plus tests. No design decision remains.
- **`opus`** — reasoning-dense work where the thinking *is* the task: subtle invariants, race
  conditions, descriptor/metaclass machinery, and the cores listed in
  [[implementation-plan#model-strategy]] (sync engine, plugin block save invariant, registry
  resolution & serve-after-resync, cross-filesystem safe move).
- **`fable`** — the top-tier model, reserved for work that has defeated or would likely defeat
  `opus`: cross-cutting audits, architecture-level analysis, or issues reopened after an `opus`
  attempt missed the mark. Expensive; use sparingly and deliberately.

> [!NOTE]
> The label records the *intended* executor at triage time. If an attempt fails and the issue is
> escalated (e.g. `sonnet` → `opusplan` → `opus`), update the label and the `## Model` section so
> the record reflects the model that actually carried the work.

## Size labels

[[[appendices.project-management#size-labels]]]

T-shirt sizes on a doubling scale, estimating **agent time with the issue's labeled model** — not
human review time. Doubling fits how estimates behave in practice (they are log-accurate, not
linear), so each bucket is meaningful rather than falsely precise.

| Label | Agent time | Meaning |
| --- | --- | --- |
| `XS` | ≤ 30 min | One-sitting mechanical change; single file plus its test. |
| `S` | 30–60 min | Small but real: a couple of files, or a behavior change with new tests. |
| `M` | 1–2 h | Needs a short plan or a verification pass (visual check, race tests). |
| `L` | 2–4 h | Multi-concern or load-bearing code; full `make qa` gate expected. |
| `XL` | > 4 h | Too big for one slice — **split into smaller issues before work starts**. |

Assignment rules:

- Size from the `## Estimate` in the issue body; the estimate assumes the labeled model (the same
  fix is sized once, not once per model).
- **Round up on boundaries for sweep-style work** — wide mechanical changes (docstring scrubs,
  rename sweeps) reliably overrun, so a "~1 h" sweep is `M`, not `S`.
- **`XL` is a flag, not a schedule.** Per the tracer-bullet methodology
  ([[implementation-plan#methodology]]), no single slice should exceed a work session; an `XL`
  issue is decomposed into `M`-or-smaller slices and then closed or repurposed as the tracking
  umbrella.
- Re-size when scope changes materially (a new precondition, a discovered consumer sweep), the
  same as any other stale metadata.
