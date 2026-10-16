# §11. Borrowing, Library-Shelf Storage, and Scheduled Archival

[[[borrowing]]]

## §11.1 The "library shelf" pattern

[[[borrowing#library-shelf]]]

The NAS holding the original content can be treated as a library shelf that's normally **closed** — deliberately
powered fully off, not just idle, to save power/wear — with content **borrowed** onto a machine when the user wants it
reachable, and the shelf reopened (powered on) only when needed again. This is a distinct, deliberate workflow,
different in kind from the **implicit offline case** ([[offline-editing#overview]]), where content becomes unreachable
with no copy made.

Borrowing is planned and user-triggered, may last an arbitrary length of time (not bounded by a trip), and its
motivation is to allow the source box to be powered fully down rather than idling — or to take the content along on
the machine that travels.

## §11.2 Mechanism: a verified copy in the node's borrow store

[[[borrowing#another-instance-role]]]

A borrowed copy is a **resumable verified copy** ([[mounts-and-storage#safe-move-rename]]) of all of one resource's
files into the **borrow store** of the node on the target machine ([[discovery-trust-access#remote-admin]]), with a
`.borrow` record beside it ([[borrowing#recording-borrows]]). While borrowed, the copy is a complete, ordinary resource:
its `.rehu` is self-describing, its sidecars are the borrowers' own, and it is edited, watched and served like any
local file for as long as it exists, however long the source stays off ([[instances-and-dedup#failure-model]]).

- **One copy per resource per machine, shared by every borrower.** There is at most one node per machine, so there is
  at most one copy of a resource on it; a second user borrowing the same UUID onto a machine that already holds it
  copies nothing and adds their entry to the `.borrow` record. The node decides where it stores borrowed material and
  how it lays it out; agents only ask it over HTTP.
- **Borrowing locally is the ordinary case**: a copy from a root into this machine's node's store. A borrow onto
  another machine is the same copy, run by that machine's node into *its* store, asked over HTTP. The target preference
  — local, the remote serving node, or both — is a setting, overridable per borrow ([[nodes#node-actions]]).
- **Borrowing is per resource and selective** — a deliberate user action, never bulk replication of the library.

Whether powering the source down and up is manual or automated (a scheduled shutdown after a quiet period, Wake-on-LAN
on demand) is still to decide when this is built.

## §11.3 Scheduled archival of a borrowed resource

[[[borrowing#scheduled-archival]]]

The user can mark a borrowed resource **to be archived on return**: rather than simply deleting the local borrowed copy,
the goal is to shrink the *original* by removing large video files, while deliberately keeping `.rehu` metadata, the
`infoXX.*` images, and other explicitly-preserved extras (e.g. code-example zips). This is a structural change to what
the resource contains, not a lifecycle/visibility change like the tagging or duplicate-review mechanisms elsewhere —
though it's recorded using the existing tagging mechanism ([[data-model#rehu-format]]) rather than a new schema field.
A few consequences worth tracking precisely:

- **"Archived" is a tag, not a new schema state.** It's applied to the resource using the same general-purpose tagging
  mechanism already used elsewhere ([[data-model#rehu-format]]), not a dedicated field or enum value.
- **`complete` is never touched, before or after archival.** Per [[data-model#rehu-format]], `complete` reflects whether
  all expected files were present *at cataloguing time* and is not revisited afterward for any reason — archiving (or
  any other later, deliberate file removal) does not flip it, set it, or otherwise interact with it. It is
  write-once-at-creation, full stop.
- **Two archival granularities.** The user can choose to archive **everything** (keep only `.rehu` and images, remove
  all video) or **selectively** (keep a chosen subset of files in addition to `.rehu`/images — e.g. one or two
  representative/interesting videos), so archival is not strictly all-or-nothing on the video content.
- **Execution is deferred until the source is reachable.** Archival is a job in the task queue
  ([[architecture-design#components]]) that stays pending, like a save for an offline share ([[sync#apply-payload]]),
  and executes the moment the source is reachable again, i.e. when the "shelf" is reopened.
- **The checksum record is purged, not flagged.** Once a file is removed by archival, its entry is deleted outright
  from the checksum record, rather than retained with an "intentionally removed" marker — the record should only ever
  describe files that are actually still present.
- **Archiving the original does not affect the borrowed copy's lifecycle.** The two are decoupled: marking/executing
  archival on the original does not automatically delete the local borrowed copy. The borrowed copy's own removal (or
  continued retention) remains a separate decision for the user to make independently.
- **The action is effectively irreversible** for the files it removes — once gone, they're recoverable only from
  another copy ([[instances-and-dedup#instance-registry]]) if one exists, not from the archived resource itself.

## §11.4 Recording borrows: the `.borrow` file beside the copy

[[[borrowing#recording-borrows]]]

A borrow is recorded **beside the copy**, in a `.borrow` file in the node's borrow store, and nowhere else — nothing is
written at the origin, so a resource on read-only media borrows too. The record is self-describing and self-cleaning:

- **It names the origin** (root id, relative path, the version borrowed, the date) so Return knows where to go and what
  the edits were based on ([[sync#apply-payload]]).
- **It lists the borrowers**, one entry per user with the date borrowed and an optional expected return — a list, not a
  flag, because one copy serves every user on that machine.
- **Return removes the user's entry**; the copy is deleted only when **no borrower is left**. An admin may return a
  resource for every borrower at once ([[discovery-trust-access#admin-portability]]). Borrow is declared, return is
  declared; the absence of an entry means not-borrowed. No heuristic inference of borrow state.
- **The `.borrow` file and the record's UUID are enough to stop a second borrow.** Before borrowing, the agent asks
  every
  reachable node (and reads this machine's own store) for its `.borrow` records and matches on the `.rehu`'s `core.id`:
  a hit for the same user refuses, a hit for another user on the target machine means *join the existing copy*. The
  agent keeps a small **per-node snapshot** of the last answer in its app folder, so a node that is away still counts as
  holding what it held when last seen. A borrow made despite a stale snapshot costs a duplicate copy, nothing more:
  Return merges per field either way.
- **A stranded entry has a visible cleanup path.** A wiped machine that never returns leaves its node's records gone
  with it and its snapshot stale; the Borrowed window shows a node not seen since a date, with *Forget* beside it. An
  expected-return date lets the window flag an overdue borrow without auto-removing it.

**Mental model — OneDrive Files On-Demand.** An archived stub (metadata + screenshots only,
[[borrowing#scheduled-archival]]) ≈ online-only placeholder; a resource on the share ≈ locally available; a borrow ≈
"always keep on this device". The analogy is good for vocabulary and breaks on authority: OneDrive's cloud is always
there, this share is deliberately switched off, which is why the borrow carries its own record and its own base
version.

## §11.5 Thin tablet and the vacation topology

[[[borrowing#vacation-topology]]]

The iOS tablet is a **pure thin web client** — deliberately, because no native app will be published for it. This has
firm consequences:

- **The tablet can never hold a borrow or any per-user offline state.** It has no node and no storage of its own; it
  only ever *views* what a reachable node serves. ("Borrow onto the tablet" is therefore not possible.)
- **Away from home, the travelling machine's node is the tablet's server.** The canonical vacation topology: a laptop
  on any OS, or the Mac mini with a portable screen, runs its agent and so its node, which holds the borrowed resources
  in its store *and* serves the web pages to the tablet, reached over LAN or the machine's hotspot. The node runs only
  while that user is logged in, which is fine ([[nodes#overview]]).
- This reinforces the off-LAN boundary ([[appendices.open-questions#still-open]]): there is no "tablet reaches home over
  the internet" path. The tablet always talks to a *local* node — a machine that is on at home, or the machine that
  travels.

## §11.6 Resolving a borrow when the resource was deleted or archived meanwhile

[[[borrowing#borrow-vs-delete]]]

While user A has a resource borrowed, user B may delete it (everything, including metadata) or archive it (keeping only
metadata, screenshots, and explicitly-selected files) on the share. Because **A's borrowed copy is a complete, valid
copy**, B's action is never destructive to A — it is a divergence to resolve on A's return, with A's copy available as
a recovery source. Return finds the origin missing, or its `.rehu` changed past the version borrowed, and offers:

- **Drop** — A agrees with B; A's local copy is discarded too.
- **Archive from local** — keep metadata/screenshots/selected files using A's copy.
- **Restore from local** — A overrides B: A's complete copy is copied back to the origin as a verified copy
  ([[mounts-and-storage#safe-move-rename]]). Every other machine learns of it through the notifier like any change.

The difference between the two cases:

- **B fully deleted:** the share has nothing; the three choices operate purely on A's copy.
- **B archived:** the share has the stub; "restore/archive from local" **merges** A's fuller copy with what B kept — A's
  copy contributes the files B dropped, the stub contributes any metadata edits B made meanwhile, through the ordinary
  conflict dialog ([[sync#compare-and-swap]]).

**B's reason, where there is one, is in the stub**: the `archived` tag and the note B left are what A reads before
deciding ([[requirements#overview]] — track *why* something was removed). A full delete leaves nothing to read; there is
no activity log to carry it, and the design does not pretend otherwise.

## §11.7 Borrowing from the agent: Available offline, Return, and the Borrowed window

[[[borrowing#agent-ui]]]

- [#405: docs: spec root caching, borrowing UI, and per-file watch progress](https://github.com/borco/rehuco/issues/405)

**Borrow is per resource, retention is per root.** Retention ([[mounts-and-storage#durable-retention]]) keeps a whole
root *browsable* while its source is off — metadata, screenshots and file structure, never content. A borrow copies
**all** of one resource's files, and is the only way to *watch* a resource whose source is offline. The two never
stand in for each other.

- **The control is an *Available offline* checkbox** on a resource — the OneDrive vocabulary §11.4 maps onto
  ([[borrowing#recording-borrows]]). Checking it borrows; unchecking it **returns**.
- **The target follows the borrow preference** — local, the remote serving node, or both — and the toolbutton menu on
  *Borrow* overrides it for one borrow ([[nodes#node-actions]]). The local node is always a valid target: the agent
  starts it if it is not running.
- **A borrowed copy lives in the node's store**, a folder of that machine's choosing — never the app's own folder
  ([[packaging-deployment#app-folders]]), since one borrow can be many gigabytes.
- **Return is always explicit, and always says what it deletes.** Unchecking asks for confirmation naming the node and
  the copy that will be removed if no borrower is left, and carries the edits back first: one apply-payload job per
  borrowed record, clean ones unattended, conflicting ones parked in Pending saves ([[sync#apply-payload]]). Nothing
  removes a borrowed copy on its own: away from home, a vanished borrow cannot be restored until the source is reachable
  again, so it must never go missing without notice. Scheduled archival ([[borrowing#scheduled-archival]]) acts on the
  original, not on the copy.
- **The *Borrowed* window lists every borrow**: per node, what it keeps (from the `.borrow` records, matched to cache
  rows
  by UUID), who borrowed it, the bytes those copies use and the free space of the node's borrow volume; the local node
  listed the same way as a remote one. A regular user sees their own borrows; an **admin sees every borrowed resource,
  its borrowers and its space, with *Return for all*** beside each. Overdue and not-seen-since entries of §11.4 show
  here.
- **A *Storage* view** shows every volume behind the roots the agent uses, grouped by volume since several roots can
  share one, with total and free space, plus each reachable node's borrow volume — so the user sees where room is
  before borrowing or moving.
- **The window also shows what each node is doing** — copying, hashing, verifying, serving web sessions — beside its CPU
  use and free memory ([[nodes#node-status]]).
- **Watching in the agent reads the content where it is stored** — the source while it is reachable, a borrowed copy
  otherwise — and progress is written to the user's sidecar beside whichever copy is being watched
  ([[field-schema#watch-progress]]); Return brings the borrowed copy's sidecar home, and the share's sidecar is what
  the web page on a node at home reads.
