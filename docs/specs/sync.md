# §7. Saves, Locks and Conflicts

[[[sync]]]

## Overview

[[[sync#overview]]]

> [!NOTE]
> **Implement the save path with Opus, not the auto-switched Sonnet.** The lock's stale rule, the compare-and-swap, the
> per-field merge and the apply-payload job's coalescing are reasoning-dense — a subtle error here silently loses or
> resurrects data. Override `opusplan` to `/model opus` while implementing this file, and verify each case against the
> rules below and the measurements of #503.

There is **no sync engine**. Until 2026-10-16 this file specified version vectors, an append-only activity log,
tombstones and a verdict queue, all resting on one node being a resource's sole writer. With the files on a share that
anyone may mount, nothing can be the sole writer, so convergence is settled where the files are: on the filesystem,
with the primitives every SMB client honours.

Two different kinds of data live beside a resource, with different natural owners:

| Data | Where | Writers | Conflict risk |
| --- | --- | --- | --- |
| Resource metadata | `info.rehu` | Anyone who edits the resource | Real but rare: two people editing the same record's details apart |
| Per-user state | `info.user-<name>.rehuser` ([[data-model#single-file]]) | That user, from any of their devices | Only between one user's devices; merges by field |

**Metadata is edited only while the file is reachable, or while a save of it has not landed.** A record whose share is
offline shows its cached details read-only ([[offline-editing#overview]]); what remains writable offline is per-user
state, through the queued jobs below, and a record whose save is still pending, which is a borrowed copy
([[sync#unlanded-save]]). The two statements that were v1's hardest promise — a single writer, and offline edits that converge — are no
longer needed: a save that cannot reach the file waits, and a save that finds the file changed is a conflict shown to
the user.

## §7.1 The lock file

[[[sync#lock-file]]]

- [#512: feat(core): the lock file and compare-and-swap in every record write](https://github.com/borco/rehuco/issues/512)

Every write to a record takes `<record>.lock` beside it — the record's own name with `.lock` added, `info.rehu.lock`
beside `info.rehu`, `catalog.rehuco.lock` beside a `.rehuco` — created with exclusive-create (`O_CREAT | O_EXCL`),
which on SMB2 is a server-side atomic create and the one locking primitive Windows, macOS and Linux clients all
honour; OS byte-range and `fcntl` locks are not that ([[appendices.post-mortem#architecture]]). Measured on the TS-230
(#503):
two Windows processes and a Mac racing 1500 attempts each, every holder reading its own id back after the hold —
1443 holds, **0 clobbered**.

- **The lock is the directory entry, never an open handle.** It is created, written (`user@host pid app time`) and
  closed in one go; its content is read back, never kept open. The reason is measured: a lock *held open* by another
  client survives its holder's exit by a minute or more on the macOS client's deferred close, a second delete of it is
  denied meanwhile, and a Windows holder blocks every delete and replace outright. The same goes for a contender
  *reading* it: a plain Windows open denies the holder's delete, which then fails and leaves every writer waiting out
  the TTL (#512, measured: 128 of 300 saves timed out), so the content is read with delete shared, and a release
  refused for a moment is retried.
- **Held for milliseconds**: the re-read → compare → atomic-replace window of one save. Create and unlink cost about
  4 ms from Windows and 13 ms from macOS over the LAN.
- **Retried with jitter, never spun.** A busy answer may be stale — the Windows client's directory cache answered
  "exists" 12–24 times per 1500 attempts for a lock that was already gone — and a hot contender starves the others
  (one Mac won 1400 of 1500 against two Windows processes). A failed create backs off a random few tens of
  milliseconds and tries again, for a bounded time, then the save waits in the queue and says so.
- **Stale by age.** A lock older than the TTL (2 minutes to start) whose content names a time that far back is broken:
  deleted, then **verified gone** — a name that lingers is treated as held and backed off from, not spun on. There is
  no heartbeat on the lock, since that would mean reopening it. A lock whose content names no time — its holder died
  between the create and the write — is aged by its modification time instead, which the 2 minutes leave far behind
  the client's cache.
- **Busy past the bound is a typed failure** naming the holder (`RecordLockedError`), which a save job turns into a
  wait: its row names the holder and tries again ten seconds later ([[sync#apply-payload]]). The back-off runs on the
  job's worker, so the lock's bound is never time the window spends frozen.
- **Excluded from scans, checksums, the Files listing, the notifier and renames**, like the staged temp files — only a
  `.lock` beside a record's name, so a tutorial's own `yarn.lock` stays content. A rename refuses while another
  process's fresh lock sits beside the record, naming the holder, and breaks a stale one.

**A `.checksum` takes the same lock** (`info.checksum.lock`), by every writer — a verify, a generate, a Forget, a claim
moved in or out ([[data-model#checksums]]). A run reads the record when it starts and hashes for minutes, so it never
writes back its own copy: under the lock it re-reads the record and merges entry by entry. What it did not change is
the file's (a claim moved in or an entry forgotten meanwhile survives), what it changed is its own, and where both
changed one entry the later `verified` date wins.

**The lock narrows the window; the compare is the safety.** A client that ignores the lock file still cannot silently
lose anyone's edit, because of the next section — it can only lose its own, which the conflict dock then shows.

## §7.2 Compare-and-swap, and the per-field merge

[[[sync#compare-and-swap]]]

Under the lock, the save re-reads the file and compares its **content hash** with the `RecordVersion` the edit was
based on ([[nodes#access-seam]]): never its modification time or size, which the Windows SMB client caches for about
ten seconds. Then:

- **Unchanged** → write the merged payload with an atomic replace ([[data-model#write-integrity]]), release.
- **Changed in per-user fields only** → merge **field by field** and write. The rules, kept from the earlier design:
  watched segments are a union; bookmarks a union by position; a video's and the tutorial's *viewed* flags a logical OR
  (*watched to the end at least once* only becomes true), except a *viewed* the user cleared by hand, which is a
  deliberate action and wins over an older true; a resume position takes the later action
  ([[field-schema#watch-progress]]); free-text notes that genuinely collide keep both and say so — and a bookmark is
  a timestamped line in those notes ([[field-schema#video-notes]]), so the two rules are one. Data is never
  silently lost.
- **Changed in the details** → the save is a **conflict**: the job fails with the conflict kept on it, and the document
  stays dirty under the conflict banner. No dialog pops while the user is elsewhere; the **next Save** first shows every
  value the two versions disagree on, the file's side as the failed save read it, with its original, the user's (the
  live document, edits made since the failed save included) and the file's; the user picks per row and saves, or
  discards their edits ([[nodes#access-seam]]). That save is checked like any other, so a file changed once more
  meanwhile fails it again. A Save on a document whose file changed on disk under its edits is a save like any other:
  its own check merges the change by field, or fails as a conflict.

**Deletion is a filesystem fact.** A record deleted on the share is gone for everyone: the notifier reports it, the
cache drops the row, a queued save for it fails and says the file is gone. **A save never recreates a folder, or the
file of a record that was read**: the folder going is the resource going, and writing it back would resurrect what
someone removed. An open document with no edits reverts, becoming the locked *missing* stub a reopen would give
([[data-model#lock-vocabulary]]); one with edits keeps them and says *The file is gone* or *The resource's folder is
gone*, and saves nothing until it is reverted, closed or the record is back — with another signature than it was read
at, the changed-on-disk rule then applies. A never-saved document says so only when its folder is gone. There are no
tombstones and nothing to resurrect; a record re-created at the same path is a new file with its own id.

## §7.3 Saves are jobs: apply a payload to a record

[[[sync#apply-payload]]]

- [#497: feat(agent): saves as jobs — apply a payload to a record, off the GUI thread, persisted, Pending saves](https://github.com/borco/rehuco/issues/497)

A save is not a call that blocks the window; it is a job on the task queue ([[appendices.task-queue]]),
`SaveRecordJob`. Save hands it a **snapshot** of the document — the record's path, whose it is, the payload to write,
the payload and `RecordVersion` it was based on, the blocks it discards, whether it is the record's first save — and the
document stays editable while it runs. Saves to one server or drive take turns in a chain of their own, saves to
another land beside them, and none waits behind a checksum run ([[appendices.task-queue#serial]]). The job:

1. Asks whether the share answers before touching it. One that does not makes the job **wait**
   ([[appendices.task-queue#waiting]]): the row says *Waiting for the share* and tries again thirty seconds later.
2. Fails, naming it, when the folder is gone or a record that was read is no longer there — it never recreates
   either ([[sync#compare-and-swap]]).
3. Takes the lock ([[sync#lock-file]]), re-reads, compares and merges ([[sync#compare-and-swap]]). A lock held
   elsewhere past its bound is a wait too, retried ten seconds later, and so is a write that failed because the share
   went away under it.
4. Writes atomically, releases and lets the notifier announce the change; then logs the blocks the save discarded, and a
   first save takes over the enclosing record's checksums ([[data-model#checksums]]).

- **One pending save per record.** A later Save hands a save that has not landed — queued, waiting, paused or failed —
  the newer data rather than queueing a second write behind it, so edits made while it waits land as one write. One
  made while the save is writing is written by the same job right after, against the version that write left, so it
  never conflicts with it. A save that landed, or was cancelled, is history: the next Save is a job of its own.
- **What the save changed comes back.** A save changes things on its way to disk — the stamps, the per-user fields
  merged from the file, a block only the file had. When it lands they are put onto the live document **except where
  the user edited since the last Save**, so the document stays dirty exactly when it was edited since.
- **A failure never pops a dialog.** A conflict fails the job with the conflict kept on it; the document shows the
  conflict banner, and the next Save shows the differences first ([[sync#compare-and-swap]]). A record whose file or
  folder went fails the job too, which keeps its payload: putting the file or folder back and pressing Retry writes it.
- **Persisted**: the payload is written with the queue's state, so a save made while the NAS was off survives quitting
  and lands when the share is back. A waiting save comes back waiting and is tried at once.
- **An interactive save is one such job.** Returning from a vacation is **N of them enqueued at once** — for every
  borrowed resource, the user's sidecar and any details edited away are payloads whose base version is the version
  borrowed ([[borrowing]]). Every clean one applies unattended; every conflicting one parks with its diff. The sidecar
  makes the common case automatic: it has one writer per user, so it only ever conflicts with that user's other device.

### §7.3.1 A save not landed is a borrowed copy

[[[sync#unlanded-save]]]

- [#497: feat(agent): saves as jobs — apply a payload to a record, off the GUI thread, persisted, Pending saves](https://github.com/borco/rehuco/issues/497)

**Until it lands, a save is a modified borrowed copy of one record** ([[borrowing#another-instance-role]]): its payload,
not the file, is the record on this machine, and landing is its Return. For a borrow the copy itself holds that state;
for a save the queued payload does. Every rule below is the borrow's.

- **The pending payload is the saved state.** Pressing Save hands the edits to it and leaves the document clean; an
  edit after that makes it dirty again. **Revert** goes back to the pending payload, **opening** the record — again, or
  after a restart, since the payload is written down with the queue — shows it, clean, under the pending-save banner,
  at once and editable whether or not the share answers ([[offline-editing#overview]]). The file is still read, in the
  background, so a document whose share answers knows what it is based on: the read fills in the file's signature and
  format version, and never what the document shows or anything edited meanwhile.
- **Closing loses only what was not saved.** Discard when closing drops the edits since the last Save; the pending
  save stays and lands later, exactly as closing a borrowed document leaves the copy.
- **Nothing drops a pending save on its own.** It leaves only by landing or by **Drop** — *Discard Save* in the Tasks
  dock, which asks first ([[borrowing#borrow-vs-delete]]). Drop returns an open document to the file, edits made since
  the last Save included, as Revert did before any save was pending. Cancelling or clearing a save row is a Drop, and a
  sweep of the dock's finished or failed rows, or a restart's, leaves failed saves alone: each still holds the edits it
  could not land.
- **The file changing meanwhile is the save's to judge.** While a save is pending, a change on disk reloads nothing: the
  save's own check finds it when it runs — merged by field, or failed as a conflict for the user to settle
  ([[sync#compare-and-swap]]).
- **A failed save is still the saved state.** A conflict, or a file or folder that went, keeps its payload as the
  record until it is settled; Save stays available on the clean document so the user can settle it, and *Inspect
  Save* does the same from the dock.
- **It follows renames.** A save of a record renamed in the app — its own folder, or a collection folder above it —
  writes where the record went. A rename made outside the app looks like a deletion, and undoing it and pressing Retry
  is the recovery.
- **A first save checks too.** A record saved for the first time that someone else created meanwhile fails as a
  conflict, its Original side empty, rather than being written over unseen.

## §7.4 Pending saves

[[[sync#pending-saves]]]

- [#497: feat(agent): saves as jobs — apply a payload to a record, off the GUI thread, persisted, Pending saves](https://github.com/borco/rehuco/issues/497)

The status bar counts the saves not yet landed — *N pending saves*, hidden at zero — and a click on it opens the Tasks
dock on its **Pending Saves** filter, the save rows neither done nor cancelled: waiting for the share, waiting for a
lock, paused, or **failed on a conflict** with its payload kept. *Inspect Save* on one failed or waiting save opens its
document — showing the row's edits, as every open of a record with a pending save does ([[sync#unlanded-save]]) — and,
if the file changed since, the differences, then saves again; *Discard Save…* asks once, drops the rows, and returns
an open document of each to its file. A document's banner says *Save pending*, *Save waiting*, *Save paused* or *Save
failed*, with the reason, for a save that has not landed — except while the conflict banner shows, which says more —
and *Saving…* while it writes. Nothing is retried behind the user's back after a conflict: the file changed under
them, and the decision is theirs. A wait is different: a root that becomes reachable again tries its waiting saves at
once.

**Closing waits for the save.** Closing a dirty document, Save All and quitting save and then wait for the write behind
a modal progress dialog, since what they gate must not go ahead of the edits; Cancel stops waiting and leaves the row.
A conflict there shows the differences; a save that cannot land asks **Try Again**, **Leave It Pending** — go ahead,
the row lands later — or **Cancel**.

**Unsaved changes can outlive a quit.** With the Session setting *Keep unsaved changes when quitting* on, quitting asks
nothing about dirty documents: their edits, and each one's dock layout, are kept in `unsaved-changes.json` in the
config folder, and the next start reopens those documents dirty with those edits, whether or not the session is
restored — at once on a local drive, once the share answers otherwise, and one whose share does not answer stays kept
for the start after. A never-saved document comes back new, bound to its path; one whose file changed meanwhile shows
the changed-on-disk banner, and its save is checked against the file; one whose file or folder is gone reopens with its edits
and the *gone* banner rather than being dropped. With the setting off, quitting asks as before; closing one document by
hand always asks Save / Discard / Cancel. What was saved is never in question at a quit: a save not landed is written
down with the queue, and comes back as the record's saved state ([[sync#unlanded-save]]).

## §7.5 Library-wide rename

[[[sync#value-rename]]]

> [!NOTE]
> **Opus, like the rest of this file.** A rename writes every record naming a value, some of them open with unsaved
> edits; the rebase below is what keeps those edits and keeps the next save from conflicting, and a subtle error in it
> loses either the edit or the rename.

Renaming a value from the Tag Browser ([[plugins#tag-browser]]) — an author, a publisher, a tag, a collection or a
learning path — rewrites every record that names it. It is a **job on the task queue** ([[appendices.task-queue]]),
not a loop in the window, and not a save: it carries no base version, because it changes one value and nothing else.

**What changes in a record.** One pure rewrite per kind, the same function wherever it runs, matching the old value
**by folded name** (`fold`, the cache's rule — the Tag Browser lists one row per folded name, so every spelling of it is
renamed):

- an author — the name of every `authors` entry, plain string or `{name, url}` record;
- a tag — every entry of `advertised_tags` and `extra_tags`;
- a publisher — the `publisher` of every source;
- a collection — the `title` of every `collections[]` entry;
- a learning path — the `title` of every **owned** entry in the current identity's scope and in the reserved `public`
  scope, and in no other user's ([[field-schema#learning-path-ownership]]); a subscription is a bare `{ref}` and
  follows by itself.

When the new value is already there, the list is **deduplicated by folded name, keeping the first** — which is the
whole of a tag merge and the member side of an entity merge ([[plugins#entity-merge]]). A record that names neither
value is not written.

**The job.** Its input is the list of records the cache says name the value (authors, tags and publishers through their
value tables; collections and learning paths through theirs, [[data-model#cache-schema]]). Each record is rewritten
under its lock ([[sync#lock-file]]) — take, re-read, rewrite, write atomically, re-read, release — and the job keeps
the version before and the version after. It **checkpoints after every record**, so a job stopped by quitting, a
pause or a share going away resumes with the records it has not done. **A record it cannot write is skipped and
named, never fatal**: locked by another writer, unreachable, unreadable or locked as a document (a newer format, an
unparseable file), or a legacy `.tc`, which is converted first. A run with skips ends failed, saying how many records
were not renamed and listing them with the reason; **Retry** runs only those — safe, because a record already renamed
reads as one with nothing to change. The cache follows each write through the notifier, so the Tag Browser's counts
move as the job runs rather than all at once.

**An open document follows, and keeps its edits.** A document open in the app may hold unsaved edits made on top of the
file the job is about to rewrite. It must end with the rename *and* the edits, still dirty, with no "changed on disk"
banner and no conflict on its next save. So the file is written first, and the document is **rebased** onto it, on the
GUI thread, from what the job hands back for that record:

1. **Only if it was based on exactly those bytes.** The document's base version must have the content hash of the
   version the job read before writing. Otherwise the file changed for some other reason as well, and the ordinary
   rules apply — a clean document reloads, a dirty one says the file changed, its save is compared as any save is.
2. **The same rewrite runs on the document's values and on its base**, the bound editors follow without marking the
   document dirty or clean — **its dirty state is untouched** — and its base version becomes the version the job read
   after writing. Its next save re-reads a file whose hash is that version: nothing to compare, no conflict, and the
   per-user merge ([[sync#compare-and-swap]]) sees exactly the user's own edits as theirs.
3. **The notifier's report of the same write is absorbed.** The change event may reach the document before the rebase
   or after it. A dirty document remembers the signature of the change it last saw; the rebase clears "changed on disk"
   when that signature is the job's own write, and a report arriving after the rebase matches the base already. A
   report of any other change keeps the banner.

A save pressed between the job's write and the rebase is an honest conflict showing the old value against the new, which
is rare and correct. A document whose file was rewritten before it was opened simply reads the renamed file. A rebase
missed (two writes with one signature) leaves the ordinary banner, never a wrong merge: the guard is the content hash.
A save payload waiting in the queue ([[sync#apply-payload]]) is rebased by the same rule before it is applied, or it
would conflict with the rename.

**Merging two entity documents** is a second job, run before the member rewrite when both A and B have documents
([[plugins#entity-merge]]): it moves A's files beside B, writes B under B's lock, and deletes A last, checkpointing
after each step. It waits while either document is open with unsaved edits — those are whole documents changing shape,
not one value, and are not rebased.
