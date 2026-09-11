# §15. Acquisition and Migration Tooling

[[[acquisition-tooling]]]

## Overview

[[[acquisition-tooling#overview]]]

These features don't belong to the core data/swarm architecture, but they're what makes the catalog *populatable and
maintainable* at scale (thousands of tutorials), so they matter for day-to-day usability. All are productivity aids
feeding the editor the user reviews — assistive, not unattended.

## §15.1 Three drag-and-drop input aids

[[[acquisition-tooling#drag-drop-aids]]]

Three drops, on three surfaces of an open document, each taking what a browser hands over. Restored from TutCatalog4,
whose QML drop areas and Scintilla drop override are the shape these follow.

- **A selection dropped on the description editor becomes Markdown at the drop point.** The drop's `text/html` is
  converted by markdownify (ATX headings, `*` bullets) and then cleaned the way tc4's converter did — unicode spaces
  normalized, a hard line break kept to two trailing spaces, runs of blank lines collapsed — because what a browser puts
  in a drag is messy. The editor substitutes the converted text for the drop's mime data and hands the drop on to
  Scintilla, so it lands exactly where a plain-text drop would; holding **Shift** skips the conversion and drops the
  plain text. Generic: no site knows about it, and it fetches nothing.
- **A URL dropped on the main editor fills the fields.** A `text/uri-list` drop, or a plain-text drop that parses as one
  `http(s)` URL, queues a scrape job ([[acquisition-tooling#scrape-job]]) and applies its result to the editor as an
  ordinary **dirty, reviewable edit** — never a save; the user reads it and decides. A selection drop whose `text/html`
  is more than the URL itself hands that fragment to the scraper as the page — the tc4 rule that let a page already
  rendered in the browser be scraped without fetching it again — with the page URL alongside, where the platform
  provides one ([[acquisition-tooling#drop-source-url]]).
- **Anything dropped on the images sub-dock ends as screenshots.** A local image file is copied in. A drop carrying
  `image/*` data is written from that data; an image URL is downloaded, with the page it came from as referrer where
  known. A page URL, or a selection, is **parsed for candidates** — `<img>` sources, the largest `srcset` entry,
  `data-src`, `og:image`, with a matching site scraper allowed to rewrite thumbnail URLs to their full-size originals —
  and shown in a **picker**: a checkable list with thumbnails, nothing downloaded until the user chooses. Every image
  then takes the same path: rescaled to a configurable maximum width (300 px by default, Pillow) and saved under the
  next free `<stem>NN.jpg` ([[data-model#image-meanings]]), which makes the drop the second client of the screenshot
  naming the conversion already serves ([[acquisition-tooling#tc-to-rehu]]). A legacy `.tc` refuses the drop, as it
  refuses every other screenshot edit. The browser's own cache is not reachable from a drop, so an image already on
  screen is fetched again rather than copied out of it.

### §15.1.1 What a drop carries, and where the page URL is

[[[acquisition-tooling#drop-source-url]]]

A browser selection arrives as `text/html` and `text/plain`, and a link or an image adds `text/uri-list`; none of the
three names the page the selection was taken from. On Windows the selection is also handed over as the `HTML Format`
clipboard format, whose header carries a `SourceURL:` line; Qt strips that header when it synthesizes `text/html`, but
the raw payload stays reachable under `application/x-qt-windows-mime;value="HTML Format"`. macOS and Linux carry no
such header for a plain selection, so there the page URL is unknown unless the user drops the link as well. **To be
confirmed by a spike** before the main-editor and images drops are built — the browser-by-platform matrix is exactly
the kind of fact that is cheaper to measure than to remember; the spike's lesson replaces this paragraph.

## §15.2 URL extraction: site scrapers, with an LLM fallback

[[[acquisition-tooling#url-extract]]]

The predecessors extracted a tutorial's fields with per-site scrapers — BeautifulSoup over a fetched or browser-rendered
page — and every one of them broke the day its site changed its markup. An earlier draft of this section replaced them
wholesale with a local LLM. The decision now runs the other way: **site scrapers are primary, and are the user's to
keep working**. The fields that matter — a title, the authors, a description with its images, a duration — sit in a
site's markup in places a few CSS selectors name exactly, and a scraper that breaks is a script the user edits that
afternoon rather than a model to re-prompt. The LLM stays, as the fallback for hosts nobody has written a scraper for
([[acquisition-tooling#llm-url-extract]]).

### §15.2.1 One Protocol per resource type

[[[acquisition-tooling#scraper-protocols]]]

Scraping is a **desktop concern** and lives in `rehuco-agent`: a productivity aid feeding the editor, not something a
node does unattended, so `rehuco-core` learns no HTTP client and no HTML parser. Three kinds of Protocol, all
structural, all plain classes:

- **`PageFetcher`** — `fetch(url) -> Page`, a `Page` being the URL asked for, the URL it resolved to, and the HTML. The
  default fetches over plain HTTP with a browser User-Agent. A **browser-driven fetcher** — a headless browser, the
  geckodriver / undetected-chromedriver route the predecessors ended on — is an opt-in extra a scraper may declare it
  needs, or that a paywalled site makes necessary: the heaviest dependency in the app should be paid for by the site
  that needs it. See [[acquisition-tooling#browser-persona]] for what it drives.
- **`SiteScraper`** — what every scraper is: `matches(url) -> bool`, a host or prefix test as tc4's `can_scrap` was, a
  `label`, and the `publisher` it fills in.
- **One Protocol per resource type** — `TutorialScraper.scrape_tutorial(page)`,
  `ReferenceImagesScraper.scrape_reference_images(page)`, `CollectionScraper.scrape_collection(page)`, one per plugin
  key ([[plugins#plugin-blocks]]). Each returns a **typed result**: field values keyed by the plugin's own field names
  ([[field-schema#resource-types]]); a Markdown description whose image links are already rewritten to the placeholder
  `<stem>NN` names the images will get, in order; and those `images` as `(name, url, referrer)` triples the image
  pipeline of [[acquisition-tooling#drag-drop-aids]] downloads. A concrete scraper implements **as many type Protocols
  as its site can serve** — ArtStation sells tutorials and reference packs from the same product page — and dispatch
  asks for the document's *current* type, skipping a scraper that matches the host but does not implement that type.

A result is a proposal. A field the scraper could not find is absent, never filled with a guess, and the editor shows
what arrived beside what was there.

### §15.2.2 The registry, and the user's own scrapers

[[[acquisition-tooling#scraper-registry]]]

Scrapers are looked up in an **ordered list**, first `matches()` wins, and the list is the **user's scripts folder
first, then the built-ins** — so a user's module overrides a shipped scraper for the same host. That is the whole answer
to brittleness: when a site changes, the fix is a `.py` file in a folder, not a release. The folder is a settings page,
**Scrapers** ([[appendices.settings-pages#category-groups]]): the folder path; a table of what loaded — module, the
hosts it matches, the type Protocols it satisfies — and, per module, the import error when it failed, since a scraper
that silently did not load is indistinguishable from one that matched nothing; and a **Reload** that re-imports without
a restart. Scripts in that folder are **trusted local code**, run with the app's own privileges; the page says so and
the app does nothing to sandbox them. Built-in scrapers ship for **ArtStation** and **Udemy** first, the two the
predecessors kept alive longest.

### §15.2.3 The browser fetcher and its persona

[[[acquisition-tooling#browser-persona]]]

The browser-driven fetcher launches a real browser through Selenium with a **persona**: a browser profile directory
of its own, under the app's config directory, that keeps its cookies and local storage between runs. That is what
lets it read a **paywalled or members-only page** — the user logs in once, by hand, and every later automated load
carries the session, the way tutcatalogpy3's driver launched Firefox on a dedicated profile. Three controls on the
Scrapers settings page ([[acquisition-tooling#scraper-registry]]) belong to it:

- **Use the browser fetcher** — off by default; when on, every scrape that does not refuse it goes through the
  browser, not only the ones a scraper declared it needs. Which browser (Firefox via geckodriver, Chrome via
  undetected-chromedriver) is a choice beside it, since bot detection differs per site and the second exists because
  the first is flagged on some.
- **Show the browser while scraping** — headless is the default; visible is how a page that came back empty is
  inspected, and how a challenge page is solved in the same profile the fetcher will use next.
- **Open the browser** — launches the persona's browser on nothing in particular, so the user can log in to a site
  and close it; the session is then the fetcher's. This is also the remedy when a session has expired, so it stays
  one click away rather than buried in a first-run flow.

The profile is a **credential store**: it lives only under the config directory, is never inside a resource folder,
and is never synced or copied by anything the app does. Sessions expire and two-factor sites re-ask; the app does
not try to keep a login alive, it only keeps the door to renewing one open.

### §15.2.4 The scrape is a job

[[[acquisition-tooling#scrape-job]]]

A drop queues one job on the app-wide task queue ([[appendices.task-queue]]), under the document's log scope so its
fetch and its parse are readable in that document's log ([[appendices.logging#scopes]]), cancellable like any other.
Its result is applied on the GUI thread, and only if the document is still open at the same path; a document closed or
renamed while its page was being fetched simply discards the result. `markdownify`, `beautifulsoup4` and `requests`
become runtime dependencies of `rehuco-agent`; the browser driver goes under an opt-in extra.

### §15.2.5 The LLM fallback, deferred

[[[acquisition-tooling#llm-url-extract]]]

For a host no scraper matches, the earlier design still stands — as a fallback, and still deferred: fetch the page text
and hand it to a small local model for **structured extraction into a fixed JSON schema**, the same typed result a
scraper returns, with no per-site code at all.

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
- Implemented as a **task-queue job** ([[architecture-design#components]]), the same one a scraper runs as
  ([[acquisition-tooling#scrape-job]]).

## §15.3 Migration: `.tc` → `.rehu` (the oldest source format)

[[[acquisition-tooling#tc-to-rehu]]]

Opening an old `.tc` file offers a **Convert** action: it writes the `.rehu` (JSON) beside a renamed `info.tc.orig`,
then renames every image the screenshot name patterns ([[acquisition-tooling#screenshot-schemes]]) match to the
number it already carries — `cover` and any unnumbered stem become `00`, `image-01` stays `01`, `file-1` becomes
`01`, `file(3)` becomes `03` — zero-padded to two digits, per the pattern's slot. A **collision** — two matched
names resolving to the same slot, or a `<stem>NN` the slot would take already present — leaves the later file
untouched under its own name rather than picking a winner — *later* meaning by the pattern list's own order
([[acquisition-tooling#screenshot-schemes]]), then by natural sort, which for the shipped set is `cover` first. There
is no tie-break between pictures and nothing is inferred, so the
one case a rule ordering cannot settle ([[acquisition-tooling#screenshot-schemes]]) is left for the images dock to
correct by hand ([[plugins#tutorial-plugin]]). Several extensions matching the same stem resolve by **pixel area**
first, then by first appearance in the app's `IMAGE_EXTENSIONS` order — the winner is renamed, the rest are left
under their own names as further collisions. Description references to a renamed image are rewritten by a string
map from old name to new, and stay **extension-less** as they always were. A legacy number **≥ 100** is left
unconverted — no resource genuinely carries that many screenshots, so a triple-digit name is someone else's
convention, not this one's. Conversion is **deterministic and idempotent**: running it again against an
already-converted resource renames nothing, since every pattern-matched name it would act on is already a
`<stem>NN`.

**Why nothing is inferred** — measured over the whole catalog, 657 `.tc` resources (2026-09-07): 148 `cover`-vs-series
pairs are **distinct pictures** and 12 are thumbnail/full-size **duplicates** of each other, and no rule order serves
both — the same filenames describe two real-world situations, and only the pictures tell them apart (#282, #283, the
slot-inference defects this design replaces). Nor can the description drive it: only 44% of descriptions reference
any image at all, 317 resources reference none, and every referenced `cover` is referenced first — so the order
cannot be read off the text either. Hence a dumb rename to the number each file already carries, and a hand
correction where that was wrong.

No screenshot is ever backed up to an `.orig` of its own — a rename is not a write, so nothing is lost by it, and
the only backup a conversion produces is `info.tc.orig`, kept for reference. This is the **first concrete use of
the read/import upgrade path ([[data-model#schema-version]])** rather than a one-off script — though a `.tc` is
*not* itself "format v0": it is a different file format that never carried a `.rehu` version to upgrade from, so
the adapter reads one and emits the **current** `.rehu` layout, stamp included (v0 means an *unstamped* `.rehu`,
[[data-model#schema-version]]). Checksum generate/verify ([[data-model#checksums]]) belongs alongside the migration
action in the same tooling.

### §15.3.1 Convert, Discard and the rollback contract

[[[acquisition-tooling#convert-mechanics]]]

Conversion is offered on an open legacy `.tc` as a single toolbar action, **Convert**, visible **only while the
document is a legacy `.tc`** (Save hides in its place); if the `.rehu` target already exists, an overwrite
confirmation precedes the write. On success the **same dock adopts the converted document in place** — no reopen
round-trip: it becomes the `.rehu`, now unlocked (the result is never `legacy_tc`, [[data-model#lock-vocabulary]]), its
dirty flag cleared and the dock's persisted identity resynced to the new path.

The conversion is the concrete importer of the migration-vs-importer split ([[data-model#schema-version]]): it **mints**
a fresh UUID `id` and seeds `created`/`updated` from the `.tc` file's mtime — identity an import owns, once
([[data-model#stable-identity]]) — and it is a **deliberate, confirmed** act, never automatic on open. Its file-system
discipline is a strict **never-overwrite, never-delete-then-write** contract, narrower now than a copy-and-back-up
scheme needed to be, because a screenshot rename is not a write and loses nothing:

- **The `.tc` is renamed to `info.tc.orig` before any new file is written** — a pre-existing `.rehu` target is
  likewise renamed aside first when overwriting.
- **Order:** back up the `.tc` → write the `.rehu` → rename each pattern-matched image to its own slot
  ([[acquisition-tooling#tc-to-rehu]]).
- **Rollback on any failure:** undo every image rename already applied, delete the `.rehu` if it was written, then
  rename `info.tc.orig` back to `.tc`, then re-raise — so a failed conversion leaves the directory exactly as it was
  found.
- **A stale-backup guard refuses to start** if a `.orig` it would write already exists — `info.tc.orig`, or the
  `.rehu.orig` an overwrite would make (a leftover from a prior interrupted run) — so a rollback target is never
  silently clobbered.

The I/O failure of a convert surfaces through the same Retry/Cancel discipline as a save ([[data-model#write-integrity]]),
as a "Conversion Failed" dialog.

Before a bulk import over a folder tree runs, a **dry-run plan** reports what it would do without writing
anything: the mapped `.rehu` payload and image rename plan for every `.tc` found, and per-resource flags
naming why a human might want to look — a rename **collision** ([[acquisition-tooling#tc-to-rehu]]), a target `.rehu`
or stale backup that would block the resource, a size/duration string that failed to parse or stayed merely advisory,
a `.tc` key the mapper does not consume, or an mtime sitting in a run's worth of near-identical ones (the signature of
a NAS restore, bulk copy, or archive extraction clobbering it, [[data-model#stable-identity]]) that would otherwise
seed `created`/`updated` from a lie. A directory holding a `.tc` is a resource and is not descended past, the
same one-resource-one-directory assumption the backup above is built on. A directory that will not list or a
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
finish. Safety is that nothing is lost by a rename and the backup above, plus a collision leaving the later
file untouched rather than guessing — a review pass, where one is wanted, is the images dock afterwards
([[plugins#tutorial-plugin]]), deliberately, one resource at a time. A blocked row starts unchecked; checking one
**is** the explicit per-row opt-in `rehu_exists` needs to proceed with `overwrite`, and the only such opt-in offered
— a `stale_backup` row cannot be unblocked this way, so checking one simply enqueues a job that fails with a
message. Cancelling mid-import cancels every job still queued outright and lets the one already running
finish on its own, so a resource is never left half-converted.

**Converting a resource converts its checksums too** (#256). The `info.sfv` a predecessor left beside the `.tc` — a
claim made when the files were known good — is seeded into an `info.checksum` as part of the conversion job, reading
no content ([[data-model#checksums]]). It is not an option: leaving it as a file nothing reads is what the seeding
step exists to end, and it costs nothing, so there is nothing to choose. No manifest means no record, and inventing
a baseline from disk instead is what the one option is for. The manifest is **retired** once its claim is in the
record ([[data-model#checksums]], #259) — renamed to an `info.sfv.orig`, which joins `info.tc.orig` as the resource's
one retained backup — so a converted resource never keeps a file that is superseded and does not say so.

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

A completed conversion keeps exactly one retained pair to act on afterwards — `info.tc.orig` and, where #259 applied,
`info.sfv.orig` — and the only remedy over them is **Discard**, permanent by design: nothing about the conversion
itself can be undone, because nothing about it was destructive in the first place. A wrong image rename is corrected
in the images dock ([[plugins#tutorial-plugin]]), by hand, one file at a time — not by reverting the whole resource
back to a `.tc`. `File ▸ Conversion Backups…` is the catalog-wide manager over these retained pairs, **one row per
resource**: the date its conversion minted, the reclaimable size, and Discard, confirmed and irreversible, run as a
task-queue job whatever the selection size. There is nothing here to filter by outcome quality, since a conversion
has none to report — the only question a row answers is *keep this small backup, or reclaim its bytes*.

The same action sits on an open converted document, as a toolbar action offered exactly while it has something to
do — the mirror of Convert's own visible-while-`legacy_tc` rule: **Discard is offered while `info.tc.orig` is
present.** A save never discards it on its own — discarding is deliberate and confirmed or it is not discarding at
all, and the `.orig` pair is the only copy of the original `.tc` (and, once retired, of the legacy manifest).

### §15.3.2 Legacy screenshot backups, retired

[[[acquisition-tooling#adopted-backups]]]

The predecessor design kept every recognized legacy screenshot as a backup and let it rejoin the numbered set one
file at a time (**Adopt**) or leave the set for good (**Delete**). The number-preserving migration ([[acquisition-tooling#tc-to-rehu]])
makes that unnecessary: nothing is renamed away from what it is, so there is no separate backup set for a screenshot
to leave. Its place is taken by the images dock listing **un-converted** pattern-matched images beside the numbered
set and offering **Convert** or **Delete** on each (#270) — the correction surface moved from "restore what
conversion set aside" to "finish what conversion left alone."

### §15.3.3 Screenshot name patterns

[[[acquisition-tooling#screenshot-schemes]]]

tc4 catalogs accumulated screenshots under several naming conventions, and which ones a given catalog holds is a
property of that catalog rather than of the format. Recognizing them is **not only a migration-time concern** — a
pattern-matched image is a screenshot beside any record, converted or not ([[data-model#image-meanings]]) — so the
patterns are a **permanent classifier** the app carries beside every `.rehu`, consulted by the content walk and the
images dock as much as by a conversion, and not put away once a catalog is fully migrated.

A pattern is an **ordinary regular expression** with a **slot convention**: one capture group names the slot the
match belongs to, read as an integer and zero-padded to two digits; no capture group means slot `00`. Matching is
**case-insensitive**, and a malformed pattern — one that fails to compile, or that carries more than one capture
group — is **skipped and flagged**, never allowed to crash a scan or a conversion over one bad entry. Patterns are an
**ordered list**, shipped with a default set and editable on the Images/Sidecar Names settings page
([[appendices.settings-pages#category-groups]], #53) as a **try-it table**: a sample-filename column beside the slot
each pattern would assign it, so an edit shows its effect on the catalog's actual names rather than only on the
regex itself (#287).

The shipped defaults, in order:

| pattern | matches | slot |
| --- | --- | --- |
| `^cover$` | `cover` | `00` |
| `^file$` | `file` | `00` |
| `^(\d+)$` | a bare number, e.g. `03` | the number |
| `^sample-(\d+)$` | `sample-01`, `sample-02`, … | the number |
| `^image-(\d+)$` | `image-00`, `image-01`, … | the number |
| `^file-(\d+)$` | `file-1`, `file-2`, … | the number |
| `^file\((\d+)\)$` | `file(2)`, `file(3)`, … — Windows duplicate numbering | the number |

The extension is matched separately from the stem, so a pattern names only the part before it. **Order decides two
things** — which pattern matches first when more than one could (an ordinary list, evaluated top to bottom, first
match wins) and, when two names want one slot, which of them takes it ([[acquisition-tooling#tc-to-rehu]]) — and
reordering the list is a real edit for both reasons. With the shipped set that second rule reads as *`cover` first*,
since `^cover$` leads the list.

**The same pattern list reaches the content walk** (#289). [[data-model#resource-scoping]]'s coverage rule counts a
pattern-matched image as a screenshot rather than content, and it is handed the same list conversion is handed —
otherwise a file a user's added pattern matches would count as content before it is recognized and as bookkeeping
after, moving `current_size` for no reason but a settings edit.

### §15.3.4 Legacy size and duration string parsing

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

The drop aids and the site scrapers are their own milestone family, **WebScrapping** ([[implementation-plan]]),
scheduled after the LocalEdit polish rather than after the web viewer as this section once said: they are single-machine
work that makes the editor faster to feed, and nothing in them waits on a node. Only the LLM fallback
([[acquisition-tooling#llm-url-extract]]) stays deferred, until a real run of unmatched hosts says it is worth a model.
Migration ([[acquisition-tooling#tc-to-rehu]]) landed in LocalEdit8 and LocalEdit9.

The HTML→Markdown drop ([[acquisition-tooling#drag-drop-aids]]) is that family's tracer: the cheapest of the three, and
the one that proves the drop seam the other two build on. None of [[acquisition-tooling#overview]] blocks the
local-viewer or tablet-watching milestones.
