# Logging — Scopes, Sinks and Buffers

[[[appendices.logging]]]

## Overview

[[[appendices.logging#overview]]]

How a log record gets from the code that wrote it to the surfaces that show it. The pieces live in
`borco_pyside/logging/` and know nothing about rehuco; what makes them useful to it is the routing
rule below, which is what lets one app show an app-wide log *and* a log per open resource without
either being a filtered copy of the other.

Prior art, and what was deliberately not carried from it, is in [[pyside-ibo#log-stack]].

## 1. A record is about something

[[[appendices.logging#scopes]]]

Every record carries a **scope**: an opaque hashable key naming the thing it is about, or nothing.
rehuco uses a document's path; nothing in the library interprets it, and two scopes are the same scope
when they compare equal.

The scope is **ambient, not passed**. An operation opens one, and every record logged inside it —
from any module, at any depth, including a library's — is placed without the call sites changing:

```python
with LogScope.open(document.path):
    convert(document)
```

This is sound because a `logging.Handler` runs synchronously on the thread that logged, so the handler
reads the same context the caller set. Naming a scope on one call (`extra={"log_scope": key}`) beats
whatever block is open, because it is the more specific statement.

> [!IMPORTANT]
> **A thread does not inherit a scope.** A worker started from inside a scoped block logs unscoped
> unless the context is carried to it deliberately: `contextvars.copy_context()` at submission, and
> `context.run(...)` in the worker. Any component that runs work on another thread on a caller's
> behalf — the task queue above all — owes its jobs that capture, or their records land under nothing
> and the resource's own log stays empty while work is being done on it.

## 2. A record has a severity, and severities come in four bands

[[[appendices.logging#bands]]]

`logging` levels are **numbers, not four constants**: `DEBUG` and friends are landmarks in a continuous
range, and any library may log at 15, at 5, or past `CRITICAL`. So `LogLevelBand` covers ranges rather
than named values — every level belongs to exactly one band, and none belongs to none:

| Band | Covers |
| --- | --- |
| `DEBUGS` | at `DEBUG` or below, including `NOTSET` and any finer level |
| `INFOS` | above `DEBUG`, up to and including `INFO` |
| `WARNINGS` | above `INFO`, up to and including `WARNING` |
| `ERRORS` | anything above `WARNING` — errors, criticals, and whatever was invented past them |

**The bands filter independently — they are four toggles, not a threshold.** All four start shown, and
each is turned on or off without regard to the others: a reader may ask for exactly the debugs and get
no infos, warnings or errors beside them, however many exist. A floor cannot express that, and asking
for debugs under one would drag in everything above them — which during a loud job is precisely the
noise the reader was trying to get out of the way. Turning all four off shows nothing, which is a state
a reader chose rather than one to be quietly corrected back.

The same four bands are what a view paints by, so the classification lives on its own rather than
inside the filter.

## 3. One bridge, many independent surfaces

[[[appendices.logging#routing]]]

`LogBridge` is the only `logging.Handler` in this stack. Sinks attach to it:

| Attached with | Sees |
| --- | --- |
| `add_sink(sink)` | every record, scoped or not |
| `add_scoped_sink(sink, scope)` | only records made under that scope |

A scoped sink is shown neither another scope's records nor unscoped ones — it is the log *of that
thing*, and a reader who wants the rest has the app-wide surface for it.

**Every surface owns its own history.** Each holds its own buffer, drops its own oldest entries, and is
cleared on its own. Clearing one says nothing about any other, and nothing about what the bridge still
holds for the next surface to attach. This is why no sink is asked for a `cleared` signal: the prior
art had one, wired so that clearing the single view also wiped the bridge's replay buffer, which with
several surfaces would mean emptying one resource's log threw away another's history.

## 4. Cache, then replay

[[[appendices.logging#replay]]]

The bridge is installed before there is a GUI, so that startup, the settings read and an early failure
are all in hand by the time anything can show them. It caches what it receives and replays it on
attach — per scope, so a resource's surface opened *after* the work was done still shows the work.

## 5. Batching and the thread boundary

[[[appendices.logging#batching]]]

A record is never dispatched where it is logged. One queued signal wakes the sinks' thread, which then
takes everything that arrived in the meantime as a single batch — so a job logging once per file over
a large tree costs one wake-up and one row insertion per batch, not one of each per record. This is
also why the sink contract takes a sequence rather than a record.

The connection is **explicitly queued, not automatic**, so a record logged on the GUI thread takes the
same path as one logged off it. No sink is entered re-entrantly from inside a log call, and a sink that
logs while handling a batch queues another batch instead of recursing.

## 6. Buffers are bounded, and say what they dropped

[[[appendices.logging#buffers]]]

Every buffer is a ring, defaulting to `DEFAULT_LOG_LIMIT` (500) — what a person actually scrolls back
through, not what fits in memory. Keeping the whole run would trade a bounded leak for an unbounded one
and hand the reader a haystack. Both the bridge and each model count what they discarded and report it,
so a surface can say *"N earlier records dropped"* rather than quietly showing less than it was given.
The count is never reset by clearing: it answers *"is anything missing"*, and clearing brings nothing
back.

Limits are settable while running and trim immediately, so a change made in a settings dialog reaches
an open, scrolled-back view rather than waiting for a restart.

> [!NOTE]
> **The bridge's buffer is also its queue.** Entries wait there for their thread, since a second,
> unbounded queue would just move the leak. So a burst longer than the bridge's limit, arriving while
> that thread is busy, loses its oldest — counted like any other overflow. Sinks are bounded too and
> would have dropped those on arrival anyway, as long as none is asked to hold more than the bridge.

### 6.1 What rehuco configures

[[[appendices.logging#configured-limits]]]

Two settings, both defaulting to 500:

- **maximum logs in the app-wide log surface** — the bridge's buffer takes this same number rather than
  being a third setting: it exists to fill that surface on attach, so a larger buffer could never be
  shown and a smaller one would truncate the replay.
- **maximum logs in each per-resource log surface** — one value, applied to every one of them.

**The value is shared; the buffers are not.** Changing it re-caps every open resource's model; it
changes nothing about what each of them holds relative to the others, or about clearing them.

The library holds neither setting. `LogModel.limit` is an ordinary per-instance property — *"all the
resource surfaces agree"* is a fact about how the app wires them, not a policy a generic table model
should invent.
