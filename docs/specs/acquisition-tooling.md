# §15. Acquisition and Migration Tooling

[[[acquisition-tooling]]]

## Overview

[[[acquisition-tooling#overview]]]

These features don't belong to the core data/swarm architecture, but they're what makes the catalog *populatable and
maintainable* at scale (thousands of tutorials), so they matter for day-to-day usability. All are productivity aids
feeding the editor the user reviews — assistive, not unattended.

## §15.1 Three drag-and-drop input aids (restored from TutCatalog4)

[[[acquisition-tooling#drag-drop-aids]]]

- **HTML selection → Markdown into the description editor.** Selecting content on a web page and dropping it on the
  description editor: the drop's `text/html` payload is converted to Markdown by a deterministic library
  (html2text-style) and inserted at the cursor. No LLM, no per-site logic, no fetching — it just transforms whatever
  HTML the browser handed over (with a sanitize/clean pass first, since pasted web HTML is messy). The cheapest and
  lowest-maintenance of the three; restore it early.
- **Image drag → download, rescale, auto-name screenshot.** Dragging an image from a browser onto a designated widget:
  download it, rescale to ≤300px wide (Pillow), and save under the next unused basename-derived screenshot name
  (`infoXX` for a directory-scoped resource, [[data-model#resource-scoping]]). No LLM. Pairs with the screenshot-name
  normalization in migration ([[acquisition-tooling#tc-to-rehu]]).
- **URL drop → extract tutorial info.** Dropping a URL: fetch/render the page and extract
  `{title, author, publisher, duration, description, …}` into the resource's fields. See
  [[acquisition-tooling#llm-url-extract]] — this is the one with real nuance.

## §15.2 URL extraction via a local small LLM

[[[acquisition-tooling#llm-url-extract]]]

The TutCatalog4 approach (geckodriver + BeautifulSoup + hand-maintained per-site scrapers) broke constantly because each
site needed bespoke parsing logic kept up to date by hand. The modern approach removes that maintenance burden: fetch
the page text and hand it to a model for **structured extraction into a fixed JSON schema**, eliminating per-site
parsing code.

- **Local model is the right call** — zero per-call cost (run thousands of times across the catalog), no external
  dependency, offline, private. This is high-volume personal productivity, where a small local model beats a cloud API
  on every axis except peak quality, and extraction doesn't need peak quality.
- **Hardware fit:** a 7–8B model at 4-bit quantization (e.g. Qwen2.5-7B-Instruct) runs comfortably on the RTX 4070 (12
  GB, fast) and on the Mac mini M1 (16 GB unified, slower but usable). Worth testing whether a 3–4B (Qwen2.5-3B)
  suffices for even more speed; reserve 14B (4070 only) for if 7B visibly struggles. Dispatch this to a capable node
  (4070 box or Mac mini), explicitly **not** the QNAP
  ([[mounts-and-storage#example-deploy]]/[[mounts-and-storage#node-benchmark]]).
- **Reliability comes from constraining output, not from model size.** Use **grammar/JSON-schema-constrained decoding**
  (llama.cpp GBNF, Ollama format, Outlines, LM Format Enforcer) so the model *cannot* emit invalid structure or extra
  fields — this removes the entire "formatting" failure class and leaves only "did it find the right value," which small
  models do well. Pair with an explicit **"return null when a field isn't present"** instruction so the model leaves
  blanks rather than hallucinating a plausible-but-wrong value. With both, a constrained 7B is "right on common cases,
  never confidently wrong" — exactly the bar for an assistive tool the user reviews before saving.
- **The harder half is fetching/rendering, not extraction.** JS-heavy course pages (Udemy, Gumroad) may still need a
  headless browser to render before extraction, and a readability/main-content trim before the model keeps quality up on
  long pages. So per-site effort drops a lot but doesn't vanish — it moves from "parse this site's DOM" (brittle) to
  "render and trim this site's page" (more robust).
- Implemented as a **task-queue job** ([[architecture-design#components]]), like other heavy work.

## §15.3 Migration: `.tc` → `.rehu` (the oldest source format)

[[[acquisition-tooling#tc-to-rehu]]]

Opening an old `.tc` file offers migration actions: convert `.tc` (YAML) → `.rehu` (JSON), and normalize the non-uniform
screenshot names into the uniform basename-derived `infoXX` scheme ([[data-model#resource-scoping]]). This is the
**first concrete use of the read/import upgrade path ([[data-model#schema-version]])** rather than a one-off script —
though a `.tc` is *not* itself "format v0": it is a different file format that never carried a `.rehu` version to
upgrade from, so the adapter reads one and emits the **current** `.rehu` layout, stamp included (v0 means an
*unstamped* `.rehu`, [[data-model#schema-version]]). Checksum generate/verify ([[data-model#checksums]]) belongs
alongside the migration actions in the same tooling.

### §15.3.1 Convert actions and the backup/rollback contract

[[[acquisition-tooling#convert-mechanics]]]

Conversion is offered on an open legacy `.tc` as two toolbar actions — **Convert, Keep Backups** and **Convert, Discard
Originals** — differing only in whether the `.orig` backups survive a successful run. They are visible **only while the
document is a legacy `.tc`** (Save and Revert hide in their place); if the `.rehu` target already exists, an overwrite
confirmation precedes the write. On success the **same dock adopts the converted document in place** — no reopen
round-trip: it becomes the `.rehu`, now unlocked (the result is never `legacy_tc`, [[data-model#lock-vocabulary]]), its
dirty flag cleared and the dock's persisted identity resynced to the new path.

The conversion is the concrete importer of the migration-vs-importer split ([[data-model#schema-version]]): it **mints**
a fresh UUID `id` and seeds `created`/`updated` from the `.tc` file's mtime — identity an import owns, once
([[data-model#stable-identity]]) — and it is a **deliberate, confirmed** act, never automatic on open. Its file-system
discipline is a strict **never-overwrite, never-delete-then-write** contract:

- **Every original the conversion touches is renamed to a `.orig` sibling before any new file is written** — the `.tc`
  itself, every recognized legacy screenshot (winners *and* losers, [[acquisition-tooling#screenshot-schemes]]), and a
  pre-existing `.rehu` target when overwriting.
- **Order:** back up all originals → write the `.rehu` → copy each winning screenshot to its new `<stem>NN` name.
- **Rollback on any failure:** delete every new file created so far, then rename every `.orig` back to its original name,
  then re-raise — so a failed conversion leaves the directory exactly as it was found.
- **A stale-backup guard refuses to start** if any `.orig` sibling already exists (a leftover from a prior interrupted
  run), so a rollback target is never silently clobbered.
- **Backups are deleted only after full success**, and only for the discard-originals variant; keep-backups leaves them
  in place.

The I/O failure of a convert surfaces through the same Retry/Cancel discipline as a save ([[data-model#write-integrity]]),
as a "Conversion Failed" dialog.

Before a bulk import over a folder tree runs, a **dry-run plan** reports what it would do without writing
anything: the mapped `.rehu` payload and screenshot rename plan for every `.tc` found, and per-resource flags
naming why a human might want to look — a screenshot tie-break, a target `.rehu` or stale backup that would
block the resource, a size/duration string that failed to parse or stayed merely advisory, a `.tc` key the
mapper does not consume, or an mtime sitting in a run's worth of near-identical ones (the signature of a NAS
restore, bulk copy, or archive extraction clobbering it, [[data-model#stable-identity]]) that would otherwise
seed `created`/`updated` from a lie. A directory holding a `.tc` is a resource and is not descended past, the
same one-resource-one-directory assumption the backups above are built on. A directory that will not list or a
`.tc` that will not read or parse costs its own entry and is named, never the whole plan — the walk says what
it could not see, the discipline the checksum sweep already follows ([[mounts-and-storage#offline-mounts]]).

`File ▸ Import Legacy Catalog…` is the wizard that runs the plan and then acts on it, over as many
resources as the folder holds — thousands, for a real catalog. Five steps: choose a root (remembering
recent ones); run the scan on a worker thread, cancellable; show the plan as a checkbox table, one row per
resource, sortable and filterable by flag, with a header summary (*"9,847 clean · 153 flagged · 12
blocked"*) and the `suspect_mtime` count named on its own line when it is not zero, since a wall of
clobbered timestamps is a reason to stop and look rather than one flag among six; enqueue one
`TcImportJob` per checked resource onto the app-wide task queue and watch them finish; then a result table
with an outcome per row and **Retry Failed**. **No per-item review gate** — the conversion offers no
choices to confirm, so a per-resource pass over thousands of items would be ceremony nobody would ever
finish. Safety is the backups and the revert above, plus every resource keeping its backups
unconditionally on this path (the discard variant is never offered here — that is the backups manager,
afterwards, deliberately). A blocked row starts unchecked; checking one **is** the explicit per-row
opt-in `rehu_exists` needs to proceed with `overwrite`, and the only such opt-in offered — a
`stale_backup` row cannot be unblocked this way, so checking one simply enqueues a job that fails with a
message. Cancelling mid-import cancels every job still queued outright and lets the one already running
finish on its own, so a resource is never left half-converted.

**Converting a resource converts its checksums too** (#256). The `info.sfv` a predecessor left beside the `.tc` — a
claim made when the files were known good — is seeded into an `info.checksum` as part of the conversion job, reading
no content ([[data-model#checksums]]). It is not an option: leaving it as a file nothing reads is what the seeding
step exists to end, and it costs nothing, so there is nothing to choose. No manifest means no record, and inventing
a baseline from disk instead is what the one option is for. The manifest is **retired** once its claim is in the
record ([[data-model#checksums]], #259) — renamed to an `info.sfv.orig` that joins the resource's retained backups —
so a converted resource never keeps a file that is superseded and does not say so.

**The scan reports a second kind of row** (#259): an already-converted resource still carrying that manifest beside
its `.checksum`, which is what hand-converting produced before retirement existed. Free to find — the walk reads every
directory's listing for the conversions anyway, and this is three names out of one listing — and executed as **one
job per resource, like the conversions**, merging the stranded claim into the record and retiring the file. It sits on
the same plan table as the conversions, because that is one resource, one job and one outcome, which is the whole of
what a row means there; it is checked by default, since nothing blocks it and no judgement is being made; and the
content-check option does not reach it, since it reads no bytes and its record lands dateless like a seeded one, which
a later sweep settles. A `.tc` in that state gets no row of its own: the conversion ahead of it carries the manifest
forward and retires it either way, and a second job against a path the first one renames away would be a race with
nothing to win.

That option is **whether to check the content**, and it is **off by default** because on it reads the whole library.
Ticked, it queues a **second job per resource** — verifying the just-seeded record where a manifest made a claim, and
generating one from disk where none did. A second job rather than more work in the first: a conversion is not safely
interruptible, since it is renaming files, and folding a multi-hour read into it would make a catalog-wide import
unstoppable. As its own job the hashing is pausable, cancellable and retryable, and stopping between the pair is
harmless — the resource is converted with a dateless record, which any later sweep settles. Cancelling the import
cancels these too, or stopping it would leave the library being read for hours afterwards. They are otherwise **not
the wizard's to report**: their outcome is not a conversion's and belongs on no row of its table, they outlive the
dialog, and the task queue is where a run measured in hours is watched. The result step says how many were queued, so
*the import is finished* is not read off a page with hours of hashing still to run.

Retained backups stay usable **after** a run, not only during one: a completed conversion can be **reverted** — the
written `.rehu` and the `<stem>NN` screenshots it installed are deleted and every `.orig` renamed back — or its backups
**discarded**, making it permanent. This is what makes an unattended bulk import safe: nothing was deleted, and every
item can be undone one at a time. The same discipline applies as to the forward direction:

- **It refuses rather than half-reverts.** No backed-up `.tc` beside the resource means this is not a conversion to
  undo; a restore target occupied by a file the revert would not itself delete — a legacy name the user has since put
  back by hand — refuses the whole operation rather than overwriting it.
- **Nothing is deleted while a rename can still fail.** The written files are moved aside first, every backup is renamed
  back, and only then are the moved-aside files deleted — so a failure part-way leaves the resource **converted**, the
  mirror of the forward rollback leaving it unconverted.
- **A revert discards edits made since the conversion**, since it deletes the `.rehu` outright. That drift is
  detectable — a conversion seeds `created` and `updated` with the same stamp and only a changed save moves `updated`
  ([[field-schema#record-timestamps]]) — so the caller can warn before losing them.
- **Backups are the directory's `.orig` siblings**, not a stem-scoped set: a legacy screenshot is named `cover.jpg` or
  `sample-01.jpg`, carrying nothing that ties it to the resource it belongs to. Exact for the directory-scoped
  resources tc4 catalogs are made of, and why a revert names a directory rather than a file.
- **A revert restores a retired manifest** (#259). The backups are restored wholesale — that is what *put the
  directory back* means — so `info.sfv.orig` becomes a live `info.sfv` again, beside the `.checksum` the conversion
  seeded from it, which a revert deliberately does not delete (it deletes only what the conversion wrote, and the
  record may since hold verify work worth keeping). This is the one door through which the manifest-beside-record
  state recurs, on a resource that is now a `.tc` again — and it heals on reconversion, which merges and retires the
  manifest whether or not a record is present. Deliberately not a scan target: the stranded rows the import wizard
  offers are `.rehu` resources only, since a `.tc`'s conversion carries its manifest forward itself.
- **And a backup is never the resource's content** (#253): the same definition is what the content walk asks
  ([[data-model#checksums]]), so the files a revert is holding are exactly the files a size scan and a checksum skip.
  Otherwise a bulk import would bake each resource's own `info.tc.orig` into its first baseline, and the discard this
  manager exists to offer would report a missing file for every resource in the catalog.

Reading what a revert *would* do — how many files, how many bytes, under what names, and whether it is possible at all
— is a separate query that writes nothing, so a surface can list retained backups without performing anything. Run
over a folder tree it becomes a **scan**, composed of that same per-resource query and the catalog walk the checksum
sweep already uses: only resources that still hold backups are reported, how many were examined survives alongside
them, and an unreadable branch is named rather than reducing the answer.

`File ▸ Conversion Backups…` is the manager over both, **grouped per resource, not per file** — six `.orig` files are
one decision, and six rows would put five of them in front of a reader who cannot act on any one alone. A row names
the resource, the date its conversion minted, what its backups amount to (*"6 files, 14 MB"*), and the flags worth a
look: a screenshot **tie-break**, a `.rehu` **edited since** the conversion, or a resource **not revertible** at all.
The header leads with the reclaimable total across the current selection, since that is the number the decision turns
on. Filtering by a flag's own word is how the review pass the bulk import deliberately skipped is actually done —
narrow to the tie-breaks, revert the few that went wrong, then select-all-discard the rest. *Select all* acts on the
filtered view, because having filtered, selecting all of *those* and selecting the whole scan are different asks.
Every action from here goes on the task queue, one job per resource whatever the selection size, so cancelling stops
after the current resource. A revert the inventory already knows cannot run is **refused on its row with the reason**
rather than enqueued to fail later, and a revert that can run is confirmed **per resource** about the edits it would
discard — never as a blanket disclaimer, which a reader can only agree to blindly. Discard, the one irreversible step
in the whole import flow, names the resource count and the byte total.

The same two remedies sit on an open converted document, as toolbar actions offered exactly while each has something
to do — the mirror of the convert actions' own visible-while-`legacy_tc` rule. **Discard is offered while backups are
retained; Revert only while one of them restores a `.tc`.** The two conditions differ precisely because backups are
any `.orig` sibling: a resource converted with its originals discarded, whose manifest had already been retired beside
it (#259), holds an `info.sfv.orig` and nothing to revert *to*, and a Revert offered there could only ever refuse. An
occupied restore target is the other refusal and keeps its button — that is a conversion which can be undone once the
file in the way is moved, and hiding it would leave a reader nothing to act on and no reason given. The inline notice
strip says what is true and nothing more ([[plugins#viewer-editor-both]]'s message-only banner discipline), so where
no revert is on offer it drops the warning about the edits one would cost. Both run inline
there: one resource is a handful of renames, and the forward conversion is already inline. **A revert adopts the
restored `.tc` in place**, the exact mirror of a convert: the same dock keeps showing the same resource, now a locked
legacy document again, re-convertible without a reopen round-trip. **A save never discards the backups** — the
divergence it creates is detectable ([[field-schema#record-timestamps]]) and is *warned about*, since discarding is
deliberate and confirmed or it is not discarding at all, and the `.orig` set is also the only copy of the original
`.tc` and of the tie-break's losers.

### §15.3.2 Legacy screenshot naming rules

[[[acquisition-tooling#screenshot-schemes]]]

tc4 catalogs accumulated screenshots under several naming conventions, and which ones a given catalog holds is a
property of that catalog rather than of the format. Conversion therefore takes an **ordered list of rules**, shipped
with a default set and editable in the agent's Legacy Screenshots settings page (#53), and renumbers the winners into
the uniform basename-derived `<stem>NN` scheme ([[data-model#resource-scoping]]).

**A rule is a series, not a filename pattern.** It has two fields: a **cover**, the literal filename stem that becomes
the series' first screenshot, and a **rest** template that the files after it match. A run of `#` in the template marks
where the number sits, and its length is that number's minimum zero-padded width — `#` counts `0, 1, … 10`, `##` counts
`00, 01 … 99, 100`, `###` counts `000 … 999, 1000`. A digit run is accepted only when re-rendering its value at that
width reproduces it exactly, so `##` takes `09` and `100` but refuses `0100`. Everything outside the `#` run is literal,
so `file(#)`'s parentheses are parentheses: a rule is never a regular expression, which is what keeps a settings string
free of both a capture-group contract and a backtracking cost.

The shipped defaults:

| cover | rest | the series it reads |
| --- | --- | --- |
| `00` | `##` | `00`, `01`, `02`, … |
| `sample-00` | `sample-##` | `sample-00`, `sample-01`, … |
| `image-00` | `image-##` | `image-00`, `image-01`, … |
| `image-01` | `image-##` | `image-01`, `image-02`, … |
| `file` | `file(#)` | `file`, `file(2)`, `file(3)`, … — Windows duplicate numbering |
| `cover` | `file-##` | `cover`, `file-01`, `file-02`, … |

**Slots are ordinal, not the numbers themselves.** The cover is slot 0; the files matching the rest template follow it
in ascending numeric order as slots 1, 2, 3, … So an `image-01`-covered series numbers `image-02` as slot 1, and `file`
is followed by `file(2)` at slot 1 — the numbering is an ordering, and a rule carries no start value to read one from.
A gap therefore closes: `00`, `01`, `05` converts to `<stem>00`, `<stem>01`, `<stem>02`.

**Which rule applies is a question about a directory, not a filename.** The two `image-##` rules above differ *only* in
their cover, and no single name distinguishes them: given `image-01.jpg` and `image-02.jpg`, the right reading is the
second rule, and the only evidence is that `image-00` is absent. So the winning rule is the **first in list order whose
cover file is present**, which is what makes the list's order significant and its reordering a real edit. A file the
winner does not recognize falls to the first other rule that does, folding into that rule's slot as a losing variant —
which is what keeps a thumbnail `cover.jpg` paired with the full-size `sample-00.jpg` it duplicates. When no rule's
cover is present at all, every rule simply participates in list order.

When several files resolve to the **same slot**, the winner is chosen by a fixed tie-break: **largest pixel area** first,
then `.jpg`/`.jpeg` preferred over other extensions, then the alphabetically-first filename. The losers are still backed
up (they are recognized files the conversion touches) but are not installed under a new name. The tie-break is **not**
part of the editable rules: it applies whatever they say.

**The same rule set reaches the content walk.** [[data-model#resource-scoping]]'s coverage rule skips a legacy record's
screenshots, and it is handed the rules the conversion is handed — otherwise a file a user's added rule renames aside
would count as content before conversion and as bookkeeping after it, moving `current_size` for no reason but a rename.

### §15.3.3 Legacy size and duration string parsing

[[[acquisition-tooling#legacy-parsing]]]

tc4 stored size and duration as human-readable strings; the reader parses them back to the canonical integer units
([[field-schema#duration-size]]), mirroring tc4's own `parsedFileSize` / `parsedDuration`:

- **Size** — base-1000 suffixes (`B`, `KB`, `MB`, `GB`, `TB`, `PB`, `EB`); the magnitude may be **fractional**, so
  `"1.5 GB"` → `int(1.5 × 1000³)` = `1500000000` bytes. A plain integer passes through unchanged; an unknown suffix, an
  unparseable magnitude, or a non-finite result yields **`None`** — omitted, never fabricated as `0`
  ([[field-schema#deferred-items]]).
- **Duration** — additive `h` / `m` / `s` tokens (`"1h 23m"` → `1×3600 + 23×60` = `4980` s); each token's magnitude must
  be an **integer** digit run (a non-numeric token contributes nothing). A plain integer passes through; absent, or a
  string in which **no** token was recognized, yields `None` — omitted, never fabricated as `0`. The single tc4
  `duration` maps into the `original_duration` slot and stays **advisory until a real scan overwrites it** — the
  untrusted-legacy-duration rule, with **no** "divide by 1000 if it looks too big" heuristic
  ([[field-schema#ms-leak-history]]).

## §15.4 Deferral

[[[acquisition-tooling#deferral]]]

Per the user's stated priorities, the acquisition aids (especially [[acquisition-tooling#llm-url-extract]]'s LLM
extraction) are **deferred until after the tutorial web viewer is working** — manual entry suffices in the interim. The
HTML→Markdown and image-drag aids ([[acquisition-tooling#drag-drop-aids]]) are cheap enough to restore earlier if
convenient, but none of [[acquisition-tooling#overview]] blocks the core local-viewer / tablet-watching milestones.
