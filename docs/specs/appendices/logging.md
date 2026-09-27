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

**Scopes nest, and a record keeps every one that was open.** An operation about a document that runs as a queued
job is about the job too, and neither surface should have to lose the other's records to exist. So a record carries
the **stack** of open scopes, innermost last — `(document.path, job_serial)` for a job enqueued from a document —
and a sink attached to a scope receives a record when that scope is **anywhere** in the stack, not only innermost.
`LogScope.current()` still answers with the innermost, and a call-site `extra=` still names one scope, which then
stands alone. The stack is the one place this library holds more than one key per record, and it is what lets the
task queue add a job scope of its own without the document's surface going quiet
([[appendices.task-queue#scopes]]).

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
| `add_scoped_sink(sink, scope)` | only records with that scope anywhere in their stack ([[appendices.logging#scopes]]) |

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

## 6. Buffers are bounded by default, and drop quietly

[[[appendices.logging#buffers]]]

A buffer is a ring, defaulting to `DEFAULT_LOG_LIMIT` (500) — what a person actually scrolls back
through, not what fits in memory. Keeping the whole run would trade a bounded leak for an unbounded one
and hand the reader a haystack.

**What falls out is not counted and not reported.** A terminal's scroll back and an editor's output pane
both truncate silently, and a reader coming from either already knows a log view is a window rather than
an archive. A count would have to be honest to be worth showing, and an honest one is not available at
the place a reader looks: what a surface can count is only its own discards, while the bridge sheds
entries of its own — sometimes before that surface ever saw them, sometimes long after it did. The
number would read as *"this is what is missing"* while meaning neither. Nothing here is actionable
either: the record is already gone, and the setting that would have kept it is the same setting whether
one entry fell out or ten thousand.

Limits are settable while running and trim immediately, so a change made in a settings dialog reaches
an open, scrolled-back view rather than waiting for a restart. That runs both ways: a buffer given a cap
takes it there and then, however it was filled before.

**A sink may be asked to keep everything** (`LogModel.limit` is `None`), and one kind is —
[[appendices.logging#configured-limits]] says which, and why that one. What makes an unbounded buffer
offered at all is **lifetime**, not size: a buffer that lives as long as the one thing it is about, and
is freed with it, is a different proposition from one that lives for the whole run.

> [!NOTE]
> **The bridge's buffer is also its queue.** Entries wait there for their thread, since a second,
> unbounded queue would just move the leak. So a burst longer than the bridge's limit, arriving while
> that thread is busy, loses its oldest. A bounded sink would have dropped those on arrival anyway, as
> long as it is not asked to hold more than the bridge, so the loss costs it nothing it would have kept.
>
> **An unbounded sink is where that stops being true.** It would have kept them, so this is the one
> place the bridge's own limit decides what a surface holds rather than merely what it replays. Whether
> the bridge's buffer should therefore be settable to unbounded too is deliberately still open.

### 6.1 What rehuco configures

[[[appendices.logging#configured-limits]]]

Two settings, both defaulting to 500:

- **maximum logs in the app-wide log surface** — the bridge's buffer takes this same number rather than
  being a third setting: it exists to fill that surface on attach, so a larger buffer could never be
  shown and a smaller one would truncate the replay.
- **maximum logs in each per-resource log surface** — one value, applied to every one of them, and the
  one that also takes **0**, meaning *keep everything*.

**The value is shared; the buffers are not.** Changing it re-caps every open resource's model; it
changes nothing about what each of them holds relative to the others, or about clearing them.

A per-resource limit set **above** the app-wide one is kept as typed but held down to it in effect: the
bridge's cache is also its queue, so entries past that number were dropped before any resource surface
could see them, and promising more would be a promise the plumbing cannot keep. The settings page says
so rather than silently correcting the number, since raising the app limit later makes the typed one
apply after all.

**Only the per-resource limit takes 0.** A loud job over a large resource — a conversion, a checksum run
— passes 500 records in one go, and what falls off the top is the beginning: the reason the rest of the
log happened. A resource surface can afford to keep the lot because it is freed when its document
closes. The app-wide surface cannot: it is fed by every resource and by the app itself, for the whole
run, which is the unbounded case §6 argues against. The clamp above does **not** apply to 0 — unbounded
is not a larger number, so it is not *above* the app limit in the sense the clamp exists for.

**0 is also the one value the clamp's guarantee stops covering.** What that guarantee buys, at every
other value, is that a surface holds exactly the number it states: since its cap is at most the bridge's,
the entries the bridge dropped during a burst are the oldest, which that surface would have discarded
itself, so the loss changes nothing about what it ends up holding. An unbounded surface *would* have
kept them. So this is the one setting under which what a log holds is decided somewhere other than by
the setting itself — which is the bridge's to fix rather than a per-resource number's, and is recorded
here rather than said again on the settings page, where it would be a paragraph to read past on every
visit.

The library holds neither setting. `LogModel.limit` is an ordinary per-instance property — *"all the
resource surfaces agree"* is a fact about how the app wires them, not a policy a generic table model
should invent. It is also where 0 stops: the library spells no cap `None`, and 0 is only the spelling a
spin box can offer, converted where the setting is read.

## 7. What a reader reads

[[[appendices.logging#surfaces]]]

One widget, hosted three times: the window's own **Log** dock, a **Log** dock inside every open resource, and a
**Log** sub-dock in the Tasks dock, attached to whichever job is selected ([[appendices.task-queue#dock]]).
All three are hidden by default and share the same icon — they are the same kind of thing about different
subjects, which is what the surrounding toolbar already says. The app-wide one is toggled from the
action bar (the top group, with the Documents and Tasks toggles) and from `View`; a resource's from its own view
toolbar, beside the inspection docks; the Tasks dock's from its own. A job's records are therefore reachable three
ways — the Tasks dock and its row, the document the job was enqueued from, and the window — because a record carries
every scope that was open when it was written ([[appendices.logging#scopes]]).

**Level and message, and the entry behind them.** The level cell is tinted by the record's band, in the
same colors the inline notice banner uses for its severities, and annotated with the record's serial.
The tint is a **wash over whatever the theme already painted**, not an opaque fill: that is what lets
one set of colors read in both light and dark instead of two tables kept in step by hand. Debugs are
left plain — there is nothing to draw attention to, and a fourth tint would make the three that mean
something harder to pick out. The message is **wrapped, not elided**: the end of a log line is usually
where the answer is.

**Following the tail is a fact about where the reader is, not a mode they set.** New records scroll into
view while the view is at the bottom, stop the moment the reader scrolls back, and resume when they
return. That is read off the scroll position rather than from wheel events, because a scrollbar drag,
`Page Up`, `Home` and a keyboard selection are all ways to leave the bottom that a wheel hook never
sees. There is still an explicit toggle, because a reader is owed a way to say *"stay at the bottom"*
without holding the scrollbar there.

**Clearing empties one surface.** Not another, and not what the bridge still holds for the next surface
to attach ([[appendices.logging#routing]]). Filtering, likewise, hides without discarding: narrowing to
errors and widening again brings back everything, including whatever arrived while the view was narrow.
What each surface saves across a restart is the reader's *view* of the log — the four bands, the search,
whether the tail is followed — never the entries, which come from the replay.

### 7.1 What is written, and what it is about

[[[appendices.logging#what-is-logged]]]

**Every condition that puts a row in a resource's inline notice banner also writes a record.** A banner
is transient and only exists while its dock is open; the log is what happened. So each lock reason is a
**warning** in the banner's own words, the upgrade offer is an **info**, and a failed rename is an
**error** — written at the transitions that produce them (a document being read, reverted, converted),
never from a property a repaint reads.

**Reading a resource is logged, not only writing one.** The one funnel both loaders and both failure
kinds pass through says either *"read, as this type"* or *"could not be read, because"* — with the
reason, since *"could not be read"* alone leaves the reader nothing to fix.

Records made about a resource are placed under its **path** ([[appendices.logging#scopes]]). A resource
renamed mid-session re-scopes its surface to the new path and keeps the rows it already showed: the
thing was renamed, not replaced. A resource with no path yet — a never-saved document — is the log of
nothing, and its first save is what gives it one.

## 8. The run log file

[[[appendices.logging#run-log-file]]]

Everything above is an in-app surface: it exists only once a `LogBridge` is installed and a dock is
open to show it. The run log file (`rehuco-agent.log`, in the app's own `config_folder()`, #362) is the
one surface that survives a run neither of those requires — a launch that only forwards its argv and
exits, or a crash hard enough to take every in-app surface down with it. It records DEBUG and up, built
on stdlib's own `logging.handlers`.

### 8.1 Several processes share the file, and only one rotates

[[[appendices.logging#run-log-file-roles]]]

The processes are one long-lived **primary** plus any number of short-lived **forwarders** — the same
split [[nodes#single-instance]] makes for the window itself. Every record carries the writing process's
pid and role (`?` before the role is known, `primary`, or `forward`), so an interleaved file still reads
as two stories rather than one confused one.

**Only the primary rotates.** A forwarder opens the file, appends its one record, and closes it again —
never holding it open — because a rename fails on Windows while another process has the file open. The
primary starts the same way, before the single-instance check resolves its role, and only *becomes*
rotating once confirmed: the same handler instance starts holding its stream open and rolling over,
rather than a second handler replacing the first, which would leave a gap and something to tear down.
If the primary's rename still fails — a forwarder mid-write — it keeps appending to what it has and
retries on the next record that crosses the size limit, rather than raising from inside a log call.
**There are no lock files.** A crash leaves nothing to clean up, at the cost of a rename racing a
forwarder rather than waiting on it — the retry above is what that cost buys back.

The file's size and backup count are ordinary settings ([[appendices.logging#configured-limits]]'s
Logs page holds them too, in a **Log file** frame of its own), read fresh on every record, so a change
applies from the very next one.

### 8.2 How a run ends is always recorded

[[[appendices.logging#run-outcome]]]

A run opens with a banner — its own id, pid, argv, and the app/platform/Python/Qt/PySide versions — and
every process installs the same hooks over `sys.excepthook`, `threading.excepthook`,
`sys.unraisablehook` and `qInstallMessageHandler`, chaining to whatever was installed before. An
uncaught exception — including one PySide re-raises from inside a Qt slot — is logged CRITICAL with its
traceback under whichever of those caught it, deduplicated so the same exception seen by more than one
layer on its way out is written once. **An exception that keeps recurring is counted, not rewritten**: a
slot raising on every repaint recurs several times a second, and its traceback written each time would
rotate the whole file away within the hour while saying nothing new — so the file gets it once, then a
count at most once a minute, and the pending count ahead of the next different exception. A `qFatal`
flushes every handler before Qt aborts, so the record that explains it is never left sitting in a buffer.

**An unclean-exit sentinel is the primary's alone.** It writes `primary.run`, naming its own run, on
becoming primary, and removes it on a clean exit. A sentinel still there at the next start names a run
that never got to say why — a native crash, End Task, or power loss — and produces a WARNING rather
than silence.

`faulthandler` is enabled on that same sentinel file, appended after its own `run=` line: a native
crash's own stack shows every thread's native frames but not one line of Python, so the dump is what
faulthandler adds — appended to the one file a fatal signal can still safely write, since it needs a
handle held open for the run's whole life, which the rotating log itself cannot offer. On an unclean
exit the next start's warning reads the sentinel back whole, so the dump rides along with the warning
it produces rather than needing a file of its own.

POSIX only, SIGTERM/SIGINT are handled through `set_wakeup_fd` + `QSocketNotifier`, turning either into
an orderly `QCoreApplication.exit`. On Windows the packaged GUI build receives no console signals at
all, and `TerminateProcess` cannot be caught from inside the process it kills — the sentinel above is
what covers those there instead.

**A Windows native crash leaves a dump only when asked to.** Windows writes a minidump for every such
crash and then deletes it, so what survives by default is the sentinel's warning and a fault offset in
the Event Log. A dump is kept only while a per-executable `LocalDumps` key exists under `HKLM`, which the
**Windows crash dumps** frame on the Windows *System Integration* page writes and removes (#363) — through
one elevated PowerShell prompted by UAC, the GUI itself never running elevated. Enabling names the
*running* executable (`rehuco-agent-dev.exe` or `Rehuco.exe`), keeps ten minidumps (`DumpType` 1, a few
MB each; never a full dump) and points them at `crashdumps/` beside the run log in `config_folder()`,
which Windows creates with the first dump. The frame's status is always read back from the registry, so a
cancelled prompt reads as *not kept* rather than as whatever the subprocess claimed; the same frame shows
the folder, what its dumps use, and clears them. Not running from a real `.exe` disables the switch, as
the key would otherwise name `python.exe` and keep dumps of every Python process on the machine.

### 8.3 What is kept out, and what is cut

[[[appendices.logging#run-log-noise]]]

Three third-party loggers are raised to INFO for every surface, not only the file — the WebDriver
traffic a scrape drives (`selenium.webdriver.remote.remote_connection`, whole page sources included),
the local HTTP calls behind it (`urllib3.connectionpool`), and a "successfully loaded extension" line
markdown writes on every render. Raising the level rather than filtering only the file keeps the same
page source out of the bridge's replay cache and the console too, not only out of this one surface.

**A single formatted line is cut past a fixed length**, with a trailing `[N chars cut]` rather than
being dropped whole — one library logging an entire payload at DEBUG should not be able to crowd a
run's earlier history out of a size-bounded file on its own, but the line that did it is still worth a
line. **A warning or worse is never cut**: a CRITICAL traceback, or the warning carrying a crashed run's
every-thread stack dump, is the record the file exists for, and it is the one a cap would otherwise
have taken the end off.
