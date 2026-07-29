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

### §15.3.2 The five legacy screenshot naming schemes

[[[acquisition-tooling#screenshot-schemes]]]

tc4 catalogs accumulated screenshots under several naming conventions; conversion recognizes **five**, matched
case-insensitively against the filename stem and mutually exclusive by prefix, and renumbers the winners into the uniform
basename-derived `<stem>NN` scheme ([[data-model#resource-scoping]]):

| scheme | example | notes |
| --- | --- | --- |
| bare zero-padded index | `00`, `01` | its own numeric series |
| `sample-N` | `sample-0`, `sample-1` | full-size series |
| `file` / `file(N)` | `file`, `file(1)` | `file` alone is index 0; the Windows-duplicate `(N)` numbers the rest; full-size |
| `cover` | `cover` | always index 0; a thumbnail variant |
| `file-N` | `file-0`, `file-1` | a thumbnail-variant series |

When several files resolve to the **same slot**, the winner is chosen by a fixed tie-break: **largest pixel area** first,
then `.jpg`/`.jpeg` preferred over other extensions, then the alphabetically-first filename. The losers are still backed
up (they are recognized files the conversion touches) but are not installed under a new name.

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
