# Project Management — Issue Labels and Sizing

[[[appendices.project-management]]]

## Overview

[[[appendices.project-management#overview]]]

How work is labeled on the [issue tracker](https://github.com/borco/rehuco/issues).
Two orthogonal label families annotate every implementation issue: a **model label** (which agent
model executes it, and in what mode) and a **size label** (how long it is expected to take that
agent). Both exist so the issue list can be triaged at a glance — pick by capability first, then by
available time — and so estimates stay comparable across issues.

Each issue's body carries the matching prose sections: a `## Model` section naming the model/mode,
and a `## Estimate` section with the expected agent time. The label is the skimmable index; the
body section is the record (and can carry a one-line rationale). Keep the two in step.

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
