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

**Metadata is edited only while the file is reachable.** A record whose share is offline shows its cached details
read-only ([[offline-editing#overview]]); what remains writable offline is per-user state, through the queued jobs
below. The two statements that were v1's hardest promise — a single writer, and offline edits that converge — are no
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
- **Busy past the bound is a typed failure** naming the holder (`RecordLockedError`), which a save job queues on
  ([[sync#apply-payload]]); until then the save fails like any other write, with Retry.
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
  ([[field-schema#watch-progress]]); free-text notes that genuinely collide keep both and say so. Data is never
  silently lost.
- **Changed in the details** → the save is a **conflict**: the job fails with its payload kept, and the conflict dialog
  shows every value the two versions disagree on with its original, the user's and the file's, the user picks per row
  and saves, or discards their edits ([[nodes#access-seam]]).

**Deletion is a filesystem fact.** A record deleted on the share is gone for everyone: the notifier reports it, the
cache drops the row, an open document locks with the reason ([[data-model#lock-vocabulary]]), a queued save for it
fails and says the file is gone. There are no tombstones and nothing to resurrect; a record re-created at the same path
is a new file with its own id.

## §7.3 Saves are jobs: apply a payload to a record

[[[sync#apply-payload]]]

A save is not a call that blocks the window; it is a job on the task queue ([[appendices.task-queue]]), with the shape
`(target key, base version, payload, merge policy)`:

1. Take the lock ([[sync#lock-file]]); wait in the queue if the share is unreachable, saying so.
2. Re-read, compare, merge ([[sync#compare-and-swap]]).
3. Write atomically, release, let the notifier announce the change.

- **One pending job per record**: a newer save for the same key replaces the pending payload rather than queueing
  behind it.
- **Persisted**: the payload is written with the queue's state, so a save made while the NAS was off survives quitting
  and lands when the share is back.
- **An interactive save is one such job.** Returning from a vacation is **N of them enqueued at once** — for every
  borrowed resource, the user's sidecar and any details edited away are payloads whose base version is the version
  borrowed ([[borrowing]]). Every clean one applies unattended; every conflicting one parks with its diff. The sidecar
  makes the common case automatic: it has one writer per user, so it only ever conflicts with that user's other device.

## §7.4 Pending saves

[[[sync#pending-saves]]]

The status bar counts the saves not yet landed, and the Tasks dock filters to them: waiting for the share, waiting for a
lock, or **failed on a conflict** with its payload kept. *Inspect* on a failed one takes the lock again, re-reads, and
opens the conflict dialog over the current file; *Discard* drops the payload. A document with a pending or failed save
says so in its banner. Nothing is retried behind the user's back after a conflict: the file changed under them, and
the decision is theirs.

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
When saves become queued jobs ([[sync#apply-payload]]), a payload waiting in the queue is rebased by the same rule
before it is applied, or it would conflict with the rename.

**Merging two entity documents** is a second job, run before the member rewrite when both A and B have documents
([[plugins#entity-merge]]): it moves A's files beside B, writes B under B's lock, and deletes A last, checkpointing
after each step. It waits while either document is open with unsaved edits — those are whole documents changing shape,
not one value, and are not rebased.
