# Task Queue — Serial Work, Cooperative Stops, and Lifetime

[[[appendices.task-queue]]]

## Overview

[[[appendices.task-queue#overview]]]

- [#201: feat: task queue engine — serialized background jobs with pause/resume/cancel/reorder](https://github.com/borco/rehuco/issues/201)

How slow work gets off the interactive path: checksum runs, directory scans, copies, bulk conversions,
and later a node's swarm chatter ([[nodes#readiness-per-op]]). The component itself is named in
[[architecture-design#components]]; this page is the half that has been built — the engine in
`rehuco_core/tasks/` — and the decisions behind it. What a reader *sees* is a dock over it, which is a
separate piece of work.

The one sentence the whole design falls out of is the component's own: *"multi-selecting serializes the
work rather than running it all at once."*

## 1. It lives in `rehuco-core`, and knows nothing about Qt

[[[appendices.task-queue#home]]]

`borco-pyside` was the obvious alternative — the logging stack lives there, and a queue is the same
*kind* of thing. Three reasons it is here instead:

- **The queue's contract is written in rehuco's own specification.** A component described in
  [[architecture-design#components]], scheduled in [[implementation-plan]], and referred to by name from
  five other specs is not generic infrastructure that happens to be useful here. `borco-core` acquired
  its guest status by being given rehuco's code early, and [[packaging-deployment#three-packages]] says
  plainly that nothing rehuco should assume the `borco-*` packages stay in this repo.
- **The node runs jobs too.** [[architecture-design#components]] gives the node *"watches folder roots,
  serves `.rehu` data over REST, participates in the swarm, **runs jobs**"* — headless, on machines with
  no display. A Qt-based engine could never be one of its pieces, and
  [[packaging-deployment#three-packages]] rejected extras precisely so that "the node has no GUI
  dependencies" stays structural rather than carefully-maintained.
- **It is what makes the engine testable.** Concurrency is the whole risk here; being able to test
  ordering, pausing, cancellation and teardown with no `QApplication` and no event loop is worth more
  than the one adapter class the split costs.

### 1.1 What an observer is told

[[[appendices.task-queue#observation]]]

**A GUI observer is the piece that buffers and marshals**, exactly as the log bridge does for records
([[appendices.logging#batching]]). The engine deliberately does none of it: it calls its listeners
synchronously, on whichever thread the change happened on, the same contract `logging` gives a handler.
A queue in front of a queue would be one more place for records — and rows — to be lost.

> [!NOTE]
> This means a job hashing a large tree calls `job_updated` once per file, on the worker thread. The
> coalescing that turns that into one repaint belongs to the observer, which is the only layer that
> knows what a repaint costs. The engine reporting less would be the engine deciding for it.

## 2. Serial by construction, not by configuration

[[[appendices.task-queue#serial]]]

One worker thread, one job in flight, and **no number to raise**. Ten checksum jobs against one disk are
slower run together than run in turn, so serialization is the specified behavior rather than a starting
value — and a `maxConcurrency` setting would be an invitation to break it.

`QThreadPool` with a count of one was considered and rejected on three counts: serial would become a
setting; a submitted `QRunnable` is no longer the queue's to reorder, so the pending list would have to
be kept outside the pool anyway; and the global pool is already shared with other background work, so
its count is not this queue's to own. A `QThread` with a worker object moved onto it was rejected for
forcing jobs to be `QObject`s, which contradicts *the engine knows none of them*.

**Whether a bounded parallel lane is ever allowed** is recorded here as answered *no, for now*, since the
issue asked for a decision rather than an assumption. If one is ever wanted — a network lane alongside a
disk lane — it is a **second queue over a different resource**, never a concurrency count on this one.
Two queues make the resource each is protecting explicit; one queue with a number makes it invisible.

## 3. A job is a plain object, and stopping is something it does

[[[appendices.task-queue#jobs]]]

A job is anything with a `label` and a `run(control)` — a `Protocol`, satisfied structurally, so a
checksum operation, a scan and a test's fake all qualify without inheriting anything. The engine knows
none of them, which is what keeps it from accumulating a case per client.

**Cancellation is cooperative, because the alternative is unsafe.** A thread cannot be killed: a job
halfway through a rename, holding a file handle, has to be allowed to unwind. So the control it is
handed offers one `checkpoint()`, and **the same call is where a pause parks it** — a job that can be
cancelled can be paused for free, and there is one place to get right rather than two.

Two consequences worth stating, because both are visible from outside:

- **A job that never checkpoints cannot be interrupted.** It runs to completion. It is still reported
  `cancelled` rather than `done` when a stop was asked for before it returned — *it could not be stopped*
  and *it ran to completion normally* are different facts, and reporting the second would be a lie about
  the first.
- **A pause does not stop anything the moment it is asked.** The queue starts no further job
  immediately, but the running one keeps running until it yields. That is why `paused` is a state of the
  *job* as well as of the queue: a job that has not reached a checkpoint yet is genuinely still running,
  and collapsing the two would hide the difference from the person watching.

### 3.1 Reordering applies to what has not started

[[[appendices.task-queue#reorder]]]

Only a queued job moves. A running one cannot be made to have started later than it did, and a finished
one has no position left to matter. A move aimed above the running job is **clamped rather than
refused**: the request is honest, only its index reaches too far, and placing a job ahead of the one
already running would promise an order the queue cannot deliver.

## 4. A failure costs its job and nothing else

[[[appendices.task-queue#failure]]]

An exception escaping a job is caught, recorded on that job as `failed` with its type and message, and
**written to the log with its traceback** — then the next job starts. A queue that stopped on the first
failure would strand every job behind it, which for a bulk conversion means one unreadable file halting
a run of thousands.

The log is deliberately where the detail lives ([[appendices.logging#what-is-logged]]): a status carries
the sentence, the log carries the traceback, and a job's records land under the scope it was enqueued in
(below), so a failure while working on a document is readable in *that document's* log.

## 5. The caller's context travels to the worker

[[[appendices.task-queue#scopes]]]

[[appendices.logging#scopes]] states the obligation this component owes and names it directly: *"Any
component that runs work on another thread on a caller's behalf — the task queue above all — owes its
jobs that capture, or their records land under nothing and the resource's own log stays empty while work
is being done on it."*

So the caller's `contextvars` context is copied at **enqueue** — not at start, which happens on the
worker where the caller's context is already gone — and the job is run inside it. `copy_context` is
generic: the engine never learns what is in a context, only that the caller's belongs to the work. That
is also what keeps this out of `borco-pyside`'s reach and leaves `rehuco-core` importing nothing new.

## 6. Nothing survives a restart

[[[appendices.task-queue#lifetime]]]

The queue is **in memory**. Quitting mid-sweep drops what was queued, and re-running it is the user's to
ask for.

Persisting it was weighed seriously — a checksum sweep over a large catalog is long enough that quitting
part-way through is normal, not exceptional. It was rejected for what it costs the job protocol: a
restorable job cannot be an arbitrary object closing over whatever it needs, it has to be a **registered
kind plus serializable arguments**, resolvable at start by a build that may no longer ship that kind.
That is a constraint on every client the queue will ever have, imposed now, to buy the resumption of one
interrupted run.

The door is deliberately left open: an *optional* serializable descriptor can be added to the protocol
later, and a job that carries one becomes restorable without any job that does not carrying the cost.
Adding it later is cheap; taking the constraint back once every client is written against it is not.

## 7. Teardown is a courtesy with a deadline

[[[appendices.task-queue#teardown]]]

Shutting the queue down cancels everything, **releases a pause first** — a parked job would otherwise
wait for a resume that is never coming — and joins the worker with a timeout. Shutdown is terminal: a
queue that has been shut down refuses further work rather than accepting jobs that will never run.

The worker is also a **daemon** thread, and that is what actually guarantees the process exits: a job
that ignores its checkpoints cannot be joined, so the wait is the chance a cooperative job gets to close
what it opened, not the mechanism that lets the app quit. A job outliving the wait is logged as a
warning rather than waited on forever — the failure this exists to prevent is a window that will not
close, and a log line is a better answer to *"why did quitting take a moment"* than a hang.
