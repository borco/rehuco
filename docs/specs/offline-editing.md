# §12. Offline Editing Without a Deliberate Checkout

[[[offline-editing]]]

## Overview

[[[offline-editing#overview]]]

Distinct from a deliberate vacation/USB checkout ([[sync#overview]]) or a deliberate borrow ([[borrowing]]): a
resource's owning
storage can become wholly unreachable (the whole box goes down, not just its node process) with **no prior checkout
having been made**. In this case, the cached entry should remain **editable for per-user state** while disconnected.

**v1 scope (per [[sync#overview]]):** the writable-cache here is a *per-user-state-writable* cache, **not** a
fully-writable one. While the resource is unreachable, the user can still edit their own notes/progress/bookmarks/borrow
records, but **resource metadata and screenshots ([[data-model#image-meanings]]) are read-only** until the authoritative
copy is reachable again. This deliberately narrows the earlier framing ("remain editable, including its images"): in v1,
images-as-screenshots are part of resource metadata and are *not* offline-editable; only per-user state is. This is what
makes [[sync#overview]]'s single-writer metadata guarantee hold without a merge tool.

The per-user-state edits accumulate locally against the last-known base and reconcile using the same rules as any other
case once the resource is reachable — generalized, per [[sync#overview]], to handle more than one independent edit
source reconciling in sequence (e.g. two different boxes each editing their own per-user state while the source was
down, reconciling one after the other once it returns — the second reconciliation merges against a state that already
includes the first).

If offline metadata editing is enabled in a future version ([[sync#overview]]'s future hook), *that* is when the
merge/diff tool and the multi-writer metadata reconciliation become necessary — they are explicitly out of scope for v1
precisely because v1 forbids the edits that would require them.
