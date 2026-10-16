# §12. Offline Editing Without a Deliberate Borrow

[[[offline-editing]]]

## Overview

[[[offline-editing#overview]]]

Distinct from a deliberate borrow ([[borrowing]]): a root's share can become unreachable — the NAS switched off, the
machine away from home — with **no copy having been made**. The cached entries stay visible and browsable from the
`.rehudb` ([[mounts-and-storage#offline-mounts]]), and what the user does with them while offline is the question here.

**Details are read-only until the file is reachable.** The `.rehu` on the share *is* the record; a cached copy of it
is not something to edit, and an edit made to it apart from the file would be the two-divergent-copies problem the
design declines to have ([[sync#overview]]). A document opened from an offline root locks with the reason
([[data-model#lock-vocabulary]]) and opens for editing again when the share comes back.

**Per-user state is always editable, through the queue.** A rating, a note, a *viewed* flag, progress watched from a
borrowed or local copy: each is a save job whose target is the user's sidecar on the share
([[sync#apply-payload]]). While the share is unreachable the job waits, persisted with its payload, counted in Pending
saves ([[sync#pending-saves]]); when the share is back it takes the lock, merges by field against whatever the user's
other devices wrote meanwhile ([[sync#compare-and-swap]]), and lands. Two machines that both edited the same user's
state while the NAS was off reconcile one after the other, each against the state the previous one left.

**A borrowed copy needs none of this.** Its `.rehu` and sidecar are local to the machine that holds it; edits land at
once, and *Return* is what carries them back ([[borrowing]]).

What the earlier design called a future "merge/diff tool for offline metadata editing" is not planned: there is no
offline metadata editing to merge.
