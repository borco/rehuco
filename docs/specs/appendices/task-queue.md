# Task Queue — Serial Work, Cooperative Stops, and Lifetime

[[[appendices.task-queue]]]

## Overview

[[[appendices.task-queue#overview]]]

- [#201: feat: task queue engine — serialized background jobs with pause/resume/cancel/reorder](https://github.com/borco/rehuco/issues/201)
- [#237: feat: per-job pause via a job cursor — plus explicit removal and retry](https://github.com/borco/rehuco/issues/237)

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

## 3. The engine schedules; the job stops itself

[[[appendices.task-queue#jobs]]]

A job is a `Protocol`. The engine orders jobs, runs one at a time, and records outcomes; **everything
about stopping belongs to the job**. Asking a running job to pause or cancel is a call *into* it —
`pause()`, `cancel()`, `resume()` — and it holds the request and acts on it wherever its own work
divides.

**Stopping is cooperative, because the alternative is unsafe.** A thread cannot be killed: a job
halfway through a rename, holding a file handle, has to be allowed to unwind. So a stop is a request
the job honors at a checkpoint it chose, and the engine learns the outcome only when `run()` returns
or raises.

An earlier design kept the request in the engine and handed the job a `control.checkpoint()` that
raised. It was replaced because of one question it could not answer: **can this stop still be taken
back?** A cancel that has merely been recorded is retractable; a cancel the job has read and begun
undoing work on is not — and that distinction lives entirely inside the job. An engine holding the flag
cannot tell the two apart, so it must either refuse every retraction or risk telling a job that is
mid-rollback to carry on. Moving the state into the job makes the question answerable by the only
party that knows: `resume()` returns whether it was in time.

> [!NOTE]
> Three methods are therefore called **on a different thread from `run()`**, and only ever on the one
> job that is running. A job that keeps mutable stop state owns its own locking — which is why
> `TaskJobBase` exists and why most jobs should inherit it rather than implement the protocol. It is
> the same eleven lines every time, and this reverses the earlier *"a plain object rather than a
> subclass"*: that was right when a job owed two members and is not right now that it owes six.

### 3.1 A paused job returns; it is not parked

[[[appendices.task-queue#cursor]]]

Pausing the running job must park it **and let the next one start**, and resuming must *continue* it
rather than start it over. The obvious reading is that the paused job's Python stack has to be kept
alive — a thread each, a run token handed between them, a rewritten worker loop. That was the first
design and it was **rejected** after reading DownThemAll's manager, which holds no continuation in
memory at all: its `resume()` simply puts the item back in the queue, and byte-level resumption is
delegated to HTTP range requests.

**A cursor does the same job here.** A job asked to pause *returns* from `run()`; on resume, `run()` is
called again and the job picks up from whatever it kept. There is no stack to hold, so:

- **The single worker thread and its loop are unchanged.** No run token, no thread per paused job, no
  N-thread shutdown join. §2 is untouched, which is the clearest evidence this was the right call.
- **In-session pause and across-restart resume are the same mechanism** — both re-enter `run()`. That is
  what makes them one feature instead of two.
- **The cost is paid selectively.** A job with nothing kept starts over, which is honest and costs
  nothing to implement; a job that wants better implements it. Nothing is imposed on every future client.

The rejected alternative would have held a Python stack and every open file handle per paused job, to
buy granularity finer than a checkpoint that nothing had asked for.

### 3.2 The job class is the unit of responsibility

[[[appendices.task-queue#job-responsibility]]]

How a cursor is shaped, where it is kept, what `run()` does on re-entry, when a stop takes effect, and
what a job undoes when it stops part-way are **one class's business**. The engine never sees a cursor
and has no opinion about one, and it does not hold the stop request either — both would put it in the
middle of something it cannot be right about. Stated as a rule because it is what keeps the protocol
from growing: **a new kind of resumable work is a new class, not a new engine feature.**

This is why `JobControl` has exactly one method. Progress is the only thing the engine genuinely needs
from a running job, because it cannot observe it and a view cannot draw without it. Everything else a
job might want to say, it says by returning or raising.

Exactly one bit crosses that boundary, and it is named for a *consequence* rather than a mechanism:
`resumes_where_it_stopped`. Nothing outside the class may assume there is a cursor at all, and the only
question a surface has a legitimate interest in is *will pausing this cost the work done so far?* — so
a dock can say so before someone pauses a forty-minute sweep that will start again.

**Starting over is a supported answer, not a defect.** A verify job that records only which manifest it
checks against is correct, and pausing it is *wasteful* rather than *wrong*. Requiring every job to
resume in place before it could be paused would be exactly the constraint-on-every-client this design
keeps refusing.

Two more declarations are read beside it, once, at enqueue: `source`, the `.rehu` this job is about —
the job's own declaration, so there is one answer and nothing to keep in step — and
`safely_interruptible`, whether stopping it part-way leaves nothing behind. That last is **distinct
from *revertible***: a conversion undoes itself on failure ([[acquisition-tooling#convert-mechanics]])
and is still not safely interruptible, because it has touched the directory. The undo is the job's own,
exactly as the cursor is; the engine only ever *asks*, and never learns what unwinding means.

### 3.3 One pause concept, and requests kept apart from states

[[[appendices.task-queue#pause-concept]]]

`pause()` asks **every unfinished job** to pause; the per-job pair asks one. There is no separate queue-wide flag, and dispatch consults per-job state only — which
is what lets pausing one job leave the rest running, and lets a job enqueued afterwards start
immediately. `queue.paused` is a **derived convenience** meaning *there is unfinished work and all of
it is paused*; it gates nothing, and it is false on a queue holding nothing unfinished, since a
vacuous truth would read as *the queue is held*.

**One request slot, not two flags.** A job is asked for at most one thing at a time and the latest
instruction replaces the one before it: asking a cancelling job to pause *downgrades* the request,
asking a pausing job to cancel escalates it. Two independent booleans could express *cancel and pause*,
which is not a state anything can act on and not a state a dock can draw. What was asked is carried on
the status as `stop_requested`, a fact separate from the state, so a watcher can be honest before the
job has obeyed.

Three consequences, all visible from outside:

- **A job that never looks at its request cannot be interrupted.** It runs to completion, and is
  reported `done` — reversing #201's *"a cancelled job must never read as done"*. The request was not
  acted on and the work genuinely finished; reporting it `cancelled` would describe an intention rather
  than an outcome. Nothing is lost, because the request is on the status.
- **A stop does not stop anything the moment it is asked.** The running job keeps running until it
  yields. That is why `paused` is a state of the *job*: a job that has not acted yet is genuinely still
  running, and collapsing the two would hide the difference from the person watching.
- **A stop can be taken back until the job has looked at it.** `resume()` on a running job asks, and
  the job answers: *not yet acted on* means it carries on as though nothing was asked, which is what
  makes Cancel-then-Resume a recoverable mis-click rather than a lost job. *Already stopping* means no
  — and it is the job that knows, because reading its request is an acknowledgement and a job reads it
  in order to start tidying up.
- **A refusal after a pause still costs only a re-entry, and the engine spends it.** The job's raise
  and the engine's recording of it are two moments with the job's own cleanup between them; a resume in
  that gap is refused, but a pause that far along has destroyed nothing, so the job is re-queued when
  the outcome lands. A refusal after a *cancel* stands: the job may already have undone work, and Retry
  is the honest recovery. Likewise a cancel arriving in that gap wins over a pause already unwinding —
  recorded onto a parked job it would be stranded, since nothing ever picks a paused job up.

**The bulk `resume()` never un-cancels anything.** It is the inverse of the bulk `pause()` and touches
only jobs whose pending request is a pause; retracting a cancel is something you ask of one row.
Sweeping a multi-selection and resurrecting a job the user cancelled ten minutes ago would be a
surprise, and the per-job call is exactly as easy to reach.

`SCHEDULED` is deliberately **not** a state: queued and scheduled are the same concept — a job waiting
its turn — and a resumed job is `QUEUED` like any other. There is likewise **no force-start**. The
queue runs exactly one job at a time, so its order already *is* the answer to "what runs next":
resuming a multi-selection schedules them all and the topmost starts, and to run a specific job now you
move it to the top. Forcing would have to mean running two things at once, which is the one thing this
component is specified not to do.

### 3.4 Reordering applies to what has not started

[[[appendices.task-queue#reorder]]]

A queued **or paused** job moves: neither is executing, both are still waiting their turn, and refusing
to move one of them would be an arbitrary difference between two jobs that are equally not running. A
running job cannot be made to have started later than it did, and a finished one has no position left
to matter. A move aimed above the running job is **clamped rather than refused**: the request is
honest, only its index reaches too far, and placing a job ahead of the one already running would
promise an order the queue cannot deliver.

## 4. A failure costs its job and nothing else

[[[appendices.task-queue#failure]]]

An exception escaping a job is caught, recorded on that job as `failed` with its type and message, and
**written to the log with its traceback** — then the next job starts. A queue that stopped on the first
failure would strand every job behind it, which for a bulk conversion means one unreadable file halting
a run of thousands.

The log is deliberately where the detail lives ([[appendices.logging#what-is-logged]]): a status carries
the sentence, the log carries the traceback, and a job's records land under the scope it was enqueued in
(below), so a failure while working on a document is readable in *that document's* log.

### 4.1 A failure is kept, because it is the thing worth acting on

[[[appendices.task-queue#kept]]]

**Jobs leave the queue only when told to. Nothing sweeps.** A failed or cancelled job is usually
retryable — a verify that ran before its generate fails for a reason that stops being true, and the fix
is to run it again — so dropping it would throw away exactly the row a reader came back for. `remove`
is the only way out, and `retry` puts a finished job back to `queued`, clears its error and progress,
and runs it **from the top**: clearing what the job kept is the whole difference between Retry and
Resume.

Re-entering a job blindly is safe because a job that changes anything guards its own re-entry — a
conversion refuses to start over a leftover backup ([[acquisition-tooling#convert-mechanics]]) rather
than trust the caller not to ask twice.

Removing the *running* job is the sharp edge. Cancellation is cooperative, so a detached job may still
be inside `run()` for a checkpoint or two; the engine **drops its terminal notification**, because
telling a listener that a row it deleted has just been cancelled would announce a job that, as far as
anyone watching is concerned, no longer exists.

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

Shutting the queue down cancels everything and joins the worker with a timeout. Shutdown is terminal: a
queue that has been shut down refuses further work rather than accepting jobs that will never run.
Nothing has to be released first — §3.1 means no job is ever parked waiting on the queue, so a paused
job is simply an unfinished one, cancelled where it stands.

**Cancelling is the wrong verb for quitting with work outstanding**, though, which is why it is not the
only thing here. The app must be closeable without anyone having to remember what they had planned, so
the exit sequence is *pause, wait, save, shut down*: `pause()` asks every unfinished job to stop,
`wait_until_idle()` waits for the running one to unwind to `paused` — at which point it has kept
whatever it needs to carry on — and only then is there a queue worth writing down. Waiting is a
separate call rather than part of `pause()` because pausing from a dock must never block the thread
drawing the dock; where the waiting happens is the caller's decision. `wait_until_idle` **reports**
rather than hangs, so a job ignoring its checkpoints leaves the caller to choose between saving what it
has and waiting longer.

> [!NOTE]
> The *save* in that sequence is not built. The engine offers the pause and the wait that make a
> clean stop possible; what is written, and where, is §6's question and is being reversed by
> [#238](https://github.com/borco/rehuco/issues/238).

The worker is also a **daemon** thread, and that is what actually guarantees the process exits: a job
that ignores its checkpoints cannot be joined, so the wait is the chance a cooperative job gets to close
what it opened, not the mechanism that lets the app quit. A job outliving the wait is logged as a
warning rather than waited on forever — the failure this exists to prevent is a window that will not
close, and a log line is a better answer to *"why did quitting take a moment"* than a hang.
