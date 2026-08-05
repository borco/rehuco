# Task Queue — Serial Work, Cooperative Stops, and Lifetime

[[[appendices.task-queue]]]

## Overview

[[[appendices.task-queue#overview]]]

- [#201: feat: task queue engine — serialized background jobs with pause/resume/cancel/reorder](https://github.com/borco/rehuco/issues/201)
- [#237: feat: per-job pause via a job cursor — plus explicit removal and retry](https://github.com/borco/rehuco/issues/237)
- [#238: feat: queue persistence — a job registry, serializable jobs, and validation on start](https://github.com/borco/rehuco/issues/238)
- [#202: feat: task queue dock — the visible queue, its context menu, and per-job controls](https://github.com/borco/rehuco/issues/202)

How slow work gets off the interactive path: checksum runs, directory scans, copies, bulk conversions,
and later a node's swarm chatter ([[nodes#readiness-per-op]]). The component itself is named in
[[architecture-design#components]]; this page covers the engine in `rehuco_core/tasks/`, the agent's
queue file over it, and now the dock that shows both (§8) — and the decisions behind all three.

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

Two more declarations are read beside it at enqueue: `source`, the `.rehu` this job is about — the job's
own declaration, so there is one answer and nothing to keep in step — and `safely_interruptible`,
whether stopping it part-way leaves nothing behind. That last is **distinct from *revertible***: a
conversion undoes itself on failure ([[acquisition-tooling#convert-mechanics]]) and is still not safely
interruptible, because it has touched the directory. The undo is the job's own, exactly as the cursor
is; the engine only ever *asks*, and never learns what unwinding means.

**`source` is the one declaration that is re-read** ([#241](https://github.com/borco/rehuco/issues/241)).
Every other answer is fixed at enqueue, because one that changed while the job ran would rewrite a row
somebody is looking at. `source` is not that kind of answer: it names *where the work is* rather than
describing the work, and a rename moves that while the job runs. A row still naming the old folder would
send a reader somewhere that no longer exists — so `resync_sources()` re-reads every job's source and
announces the ones that moved. Whoever performed the rename calls it; the queue does not go looking, and
never learns what a rename coordinator is.

That re-read **overlaps `run`**, unlike everything else here, so a job whose source can move must answer
from something safe to read on another thread. That is what a `ResourceLocation` is for, and why such a
job holds one instead of a path.

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

## 6. The queue survives a restart, for the jobs that opt in

[[[appendices.task-queue#lifetime]]]

- [#238: feat: queue persistence — a job registry, serializable jobs, and validation on start](https://github.com/borco/rehuco/issues/238)

The queue is **written to disk**, and behaves like a download manager's: close the app, reopen it, the
list is still there. Nobody has to remember what they had planned, and nobody is held hostage by a
running queue at shutdown.

**This reverses what this section said until #238**, and the reversal is recorded with both halves so
the trade stays visible. The old text rejected persistence because it *"would make every job a
registered kind plus serializable arguments — a constraint on every future client, bought for the
resumption of one interrupted sweep."* The **cost** it named is real and is now accepted — but only by
the jobs that opt in. The **benefit** was misjudged: it is not the resumption of one sweep, it is not
losing planned work and not being unable to quit.

### 6.1 A second protocol, not a wider one

`TaskJob` is unchanged. `PersistableTaskJob` extends it with `kind`, `validate()`, and the
`capture_state()` / `restore_state()` pair. **A job satisfying only `TaskJob` is legal** — it is simply
not saved — and `JobStatus.persistable` says so on every row, so a surface can mark what is about to be
lost rather than let it vanish at quit. That opt-out has to survive: a silent close depends on knowing
whether a prompt is owed.

`capture_state()`/`restore_state()` rather than a payload property plus a `from_payload` classmethod:
the pair is symmetric, and it is the same pair §3.1's cursor already implies — so **in-session pause and
across-restart resume stay one concept** instead of becoming two. It costs the registry a factory per
kind, which is what the classmethod would have saved.

`capture_state()` is specified as **called only when the job is not running**, so it never reads state
that is mutating on the worker thread. The engine keeps the last state it captured, so a queue written
*while* a job runs still holds that job — as of the last moment it could safely be asked.

**`kind` is a stable string, not a class path.** A class path bakes today's module layout into the
user's saved queue, and this repo has already moved its packages once (#157). `TaskJobRegistry` is the
indirection that turns a rename into a one-line map change instead of an unreadable file. It hands out
restored jobs through one call rather than a blank instance plus a separate restore, because a job that
has been built but not restored is an invalid object; an unknown kind answers `None`, matching
`PluginRegistry.resolve`'s house style rather than raising. Registration belongs to whoever owns the
job.

**The job class is the unit of responsibility** (§3.2, and it governs here too): how a job captures
itself, what that state holds, and how it picks up on reconstruction are one class's business. The
registry, the queue and the file know only `kind` and an opaque blob, and nothing in between inspects
one — the class that wrote a state is the class that reads it.

> [!NOTE]
> The constraint the old §6 warned about is genuine, and whoever writes the first persistable job pays
> it: the state may hold only what survives a round trip through JSON, and `kind` is a promise that
> cannot be casually renamed.

### 6.2 What is written, and when

**Everything persistable is written, including `done`, `failed` and `cancelled`.** Since jobs leave only
when removed (§4.1), dropping the finished ones at quit would be exactly the implicit removal that rule
exists to prevent — and it would take the retryable failures with it. Each item carries `kind`, the
captured state, the label, the state it was in, and the reason it failed.

**Progress is written for a job that declares `resumes_where_it_stopped`, and only for that job.** Such
a job genuinely is as far along as its bar says, because whatever it needs to carry on is in the state
it captured. A job that starts over comes back at zero, because restoring a bar the first checkpoint is
about to reset would be a lie with a witness. Note that nothing here asks *how* a job resumes, only
whether it says it does.

**Written on structural change, never on progress.** Enqueue, remove, reorder, retry, state transitions,
shutdown — O(jobs), not O(work units), so a five thousand file checksum sweep writes about twice rather
than five thousand times. What is being avoided is **`fsync` latency on the worker thread**, not SSD
wear: the file is tens of KB and endurance is a non-issue, but an atomic write is a durability barrier
by design (~0.1–1 ms on SSD, 5–15 ms on spinning disk, worse on an SMB mount) and the page cache cannot
absorb it.

The file is **JSON beside the settings file** — `task-queue.json` in the settings directory, written
through `borco_core.atomic_write_text`. Not `QSettings`, whose flat key space would spell an opaque job
state as `tasks/3/state/paths/7`. A corrupt or unreadable file logs and starts empty; it never blocks
startup.

### 6.3 What happens on the way back

**`validate()` runs before *every* start, not only after a restore.** One rule then covers both the
restored-resource-is-gone case and the deleted-while-queued one. A non-`None` return puts the job in
`failed` with that sentence as its error — no seventh state — and because a failed job is kept and
retryable (§4.1), the recovery is to fix the cause and press Retry.

**Unfinished jobs come back `paused`; finished ones keep their state.** So a restarted app comes up with
everything held, while a **newly added job runs immediately**, because eligibility is per-job and
nothing else is eligible. Which state unfinished work returns in is an argument rather than a decision
the engine makes, so a *resume tasks on restart* setting has somewhere to stand; likewise the load path
is a plain list the surface filters, not a sealed `queue.load_from(path)`.

**An unknown `kind` is dropped with a logged warning and a count**, not an error: a queue file from a
newer build, or one naming a removed feature, must not stop the app starting. The same is true of a
record that is not shaped like one at all, since what arrives came off a disk anyone can edit.

**`restore` is refused on a queue that already holds jobs, or one that has been shut down.** It is a
startup operation; making it merge invites a subtler question about identity and order that nobody has
asked.

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
> The *save* in that sequence is §6: the engine hands over what to write, and the surface that owns the
> file writes it.

The worker is also a **daemon** thread, and that is what actually guarantees the process exits: a job
that ignores its checkpoints cannot be joined, so the wait is the chance a cooperative job gets to close
what it opened, not the mechanism that lets the app quit. A job outliving the wait is logged as a
warning rather than waited on forever — the failure this exists to prevent is a window that will not
close, and a log line is a better answer to *"why did quitting take a moment"* than a hang.

## 8. The dock is a pure view, and re-snapshots rather than replays

[[[appendices.task-queue#dock]]]

- [#202: feat: task queue dock — the visible queue, its context menu, and per-job controls](https://github.com/borco/rehuco/issues/202)

`rehuco_agent.tasks.TaskQueueModel`/`TaskQueueWidget` are what a reader sees; every decision here is
about *drawing* the engine's state, never about deciding it. No control here changes its own state —
each calls into the queue and waits for the engine to say what happened.

**The observer re-snapshots rather than replays** (§1.1). The engine's five listener methods all
collapse to *something changed*; on the next GUI-thread turn, the model takes a fresh `queue.jobs()` and
diffs it against what it is holding. Per-serial last-wins coalescing — the cheap way to replay — is
unsound the moment a reorder or removal interleaves with an update, and keeping it correct needs an
ordered op-log that coalesces almost nothing. Re-snapshotting is correct by construction: the model is
always exactly the queue at a recent instant. Removals and insertions are drawn as row operations, so a
bulk enqueue of thousands of jobs costs one insertion rather than one per row; an actual reorder — rare,
and only ever from an explicit Top/Up/Down/Bottom click, never from progress — is a full model reset,
trading its row-level animation for a diff that cannot be gotten subtly wrong.

**Marshalling is a nested `Marshaller(QObject)` with one payload-free signal on an explicit
`QueuedConnection`**, the same shape `LogBridge` uses for records. Explicit-queued is load-bearing: a
control clicked on the GUI thread re-enters a listener method synchronously and must still take the
queued path, which is what makes "the view follows the engine, not its own optimistic guess" mechanical
rather than a discipline someone has to remember.

**Reorder is buttons only, no drag-and-drop.** Qt's internal-move drag-and-drop needs the *model* to
perform the move, contradicting a pure view; the engine clamps an out-of-range move, so a drop would
visibly spring back; and buttons are the only usable gesture at thousands of rows.

**A failed job's reason draws in the progress column**, elided, with the full string as the row's
tooltip — that column carries nothing useful for a failed row, and a fourth column would be blank on
nearly every row. Progress for a job that cannot estimate its total draws an honest indeterminate bar:
`total is None` and `total == 0` both read as busy, and `done > total` clamps the bar to full while the
numbers underneath still disagree, since the engine clamps nothing.

**No force-start**, matching §3.3: the queue runs exactly one job at a time, so its order already is the
answer to *what runs next*. Resuming a multi-selection schedules them all and the topmost starts; to run
a specific job now, move it to the top and resume it.

**Pausing informs, it never blocks.** The dock reads one bit — `JobStatus.resumes_where_it_stopped` —
and knows nothing about *how* any job resumes; that is the job class's own business (§3.2). A row that
does not resume where it stopped says so on its tooltip and on the Pause action. Starting over is
*wasteful, not wrong*, so there is no prompt: pausing destroys time, not data, and a modal on every pause
of a cheap job would be worse than the thing it warns about. Cancel is the one action that prompts, and
once per batch rather than once per row.

**Resume is offered for a paused job, and for a running job with a stop pending.** `resume_job` answers
whether the stop was still retractable, so Cancel-then-Resume is a recoverable mis-click while the job
has not yet looked at the request. A `False` answer is not shown as a failure — the row simply carries on
to its real outcome, no prompt and no optimistic redraw.

**The bulk clears are the dock's own sweeps, not an engine feature.** #237 deleted `clear_finished()`
because deciding *which* jobs a sweep drops is a view's business: *Clear done jobs* and *Clear failed
jobs* filter `queue.jobs()` and call `queue.remove(*serials)`; *Clear all jobs* cancels whatever is
unfinished first. There is no *clear cancelled jobs on restart* — a cancelled job was stopped on purpose
and is the one most likely to be retried, and *Clear all jobs* already covers a clean slate.

**Three restart-time settings, all off by default** (`Settings > Tasks`, `TasksSettings`): *clear done
tasks*, *clear failed tasks*, and *resume tasks*. The two clears are **applied at load, before
`restore()`** — a setting turned on after the app was last closed is honoured on the very next start
rather than the one after, since deciding at quit would make the checkbox appear not to work until the
second restart, and the dropped jobs never enter the queue at all, so there is no `jobs_removed` churn
and no flash of rows vanishing as the window opens. *Resume tasks on restart* decides which of the two
legal restored states (§6.3) unfinished work comes back in: `queued`, so the topmost starts immediately,
or the default `paused`.

**The bulk pair mirrors its own calls, not `queue.paused`.** That property is a *derived convenience*
meaning **every** unfinished job is held (§3.3), so one job paused beside one still running makes it
`False` — and gating Resume All on it would disable a resume the engine would happily perform. Each
control therefore reads the predicate its own call uses: Pause All is offered while any unfinished job
has not been asked, Resume All while any job is paused or pausing.

**Closing the app runs the exit sequence from §7** — `pause()`, `wait_until_idle()`, the store's `save()`,
the model's `detach()`, then `shutdown()` — before the outer dock layout is captured, so a floating queue
dock's visibility is never written mid-teardown. The observer detaches *before* `shutdown()`: shutdown
synchronously emits `job_updated` for each job it cancels, and each would otherwise schedule a wake-up
whose dispatch runs against a model whose widget is already being torn down.

**Quitting is silent unless it would actually cost something.** If every unfinished job is
`safely_interruptible` *and* `persistable`, the queue is written and the app quits with no prompt — being
asked every time is exactly the friction persistence exists to remove. A prompt appears only for the two
ways work is genuinely lost, each read off the job's own declaration: one that cannot be stopped
part-way without leaving something behind, and one that is not saved and so is dropped rather than
restored — which is what `JobStatus.persistable` is on every row for (§6.1). **"Wait for them to finish"
is never offered**: a modal blocking on an unbounded disk walk is a window that will not close, so the
only answers are to quit anyway or to go back and deal with the work.

**Out of scope, filed separately:** a status-bar indicator for the queue running while the dock is
hidden ([#239](https://github.com/borco/rehuco/issues/239)) — it needs an `addPermanentWidget` seam this
dock does not have and no existing precedent to follow.

**A rename is never refused because a job is running** ([#241](https://github.com/borco/rehuco/issues/241)).
[#240](https://github.com/borco/rehuco/issues/240) briefly locked the location editor while an unfinished
job's `source` sat among the paths a rename would move; on a deep sweep that is minutes to hours of not
being able to rename a folder, and with several people using the app potentially never. It is reversed
rather than tuned: jobs cooperate with a rename instead of blocking it, which is #241's whole subject.
Scheduling the rename as a job that runs once the scan releases is the same failure in a different shape
and is rejected for the same reason.
