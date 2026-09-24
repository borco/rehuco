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
- **A URL dropped on the main editor fills the fields.** A `text/uri-list` drop, a `text/x-moz-url` link/address-bar
  drop, or a plain-text drop that parses as one `http(s)` URL, queues a scrape job
  ([[acquisition-tooling#scrape-job]]) and applies its result to the editor as an ordinary **dirty, reviewable edit** —
  never a save; the user reads it and decides. A selection drop whose `text/html` is more than the URL itself hands
  that fragment to the scraper as the page — the tc4 rule that let a page already rendered in the browser be scraped
  without fetching it again — with the page URL alongside, where the platform provides one
  ([[acquisition-tooling#drop-source-url]]). A selection with no URL anywhere in it — every Firefox selection,
  §15.1.1 — has nothing to route a scrape by and is refused outright, the same as any drop this rule doesn't
  recognize.
- **Anything dropped on the images sub-dock ends as screenshots.** A local image file is copied in, every recognized
  image file of a multi-file drop in turn. A drop carrying `image/*` data is written from that data. A URL whose own
  path ends in a recognized image extension is downloaded, with the page it came from as referrer where the drop names
  one ([[acquisition-tooling#drop-source-url]]) — a link and an image arrive as the same bare `text/uri-list` URL, so
  the extension is the only signal that tells them apart. Any other URL is read as a **page**: a site scraper matching
  its host ([[acquisition-tooling#scraper-registry]]) is run for its `images` alone, its fields and description thrown
  away, and every image it names is downloaded into the slot it assigns — how a resource's screenshots are re-fetched
  from their source page without touching the rest of its record. A page no scraper matches is refused, with a banner
  row that says so and points at the picker. Holding **Ctrl** while dropping a page URL or a selection, matched or
  not, has it **parsed for candidates** instead — `<img>` sources, the largest `srcset` entry, `data-src`,
  `og:image`, with a matching site scraper allowed to rewrite thumbnail URLs to their full-size originals — and shown
  in a **picker**: a checkable list with thumbnails, nothing downloaded until the user chooses. Ctrl is the modifier
  for now, configurable once the shortcut settings exist. Every image then takes the same path: its bytes are
  **written exactly as acquired**, never decoded, rescaled or re-encoded, so a GIF keeps its animation and the file
  keeps its own extension. A plain drop lands on the next free `<stem>NN` ([[data-model#image-meanings]]), one past
  the highest, which makes the drop the second client of the screenshot naming the conversion already serves
  ([[acquisition-tooling#tc-to-rehu]]). A scraped image lands on the slot its scraper assigned, and a file already
  there is **backed up, never overwritten**: renamed to `<stem>NN.<ext>.orig`, or, when that is taken, to
  `<stem>NN.2.<ext>.orig`, `.3.`, and so on — the counter sits before the extension so every backup still ends in
  `.orig`, and the one Discard of [[acquisition-tooling#convert-mechanics]] covers these and a conversion's alike.
  The set holds `<stem>00` to `<stem>99`: an image that would need a slot past `99` is refused, logged as a warning
  in the document's log, and named in a warning row on the document's banner. A download runs on the scrape job's own
  pool ([[acquisition-tooling#scrape-job]]), not the app-wide task queue, and its result is written only if the
  document is still open, at the same path, and unlocked. A legacy `.tc` refuses the drop, as it refuses every other
  screenshot edit. The browser's own cache is not reachable from a drop, so an image already on screen is fetched
  again rather than copied out of it.

### §15.1.1 What a drop carries, and where the page URL is

[[[acquisition-tooling#drop-source-url]]]

Measured on Windows with Firefox, Chrome and Edge (`spike`, #263); macOS and Linux not yet tried.

**In Firefox**, a **page selection** — plain text or one that includes an `<img>` — arrives as `text/html` and
`text/plain` (plus Firefox's own `text/_moz_htmlcontext`/`text/_moz_htmlinfo` hints) and nothing else beyond the two
Windows drag-cursor mimes (`DragImageBits`/`DragContext` — the on-screen drag thumbnail, not payload). No format on
this drop names the source page: `application/x-qt-windows-mime;value="HTML Format"` — the raw clipboard payload a
`SourceURL:` header was expected to live in — never appears on any selection drop tried, because the browser never
offers that format as a *drag* format, only as a copy-to-clipboard one, so there is nothing for Qt to strip. A
selection containing an `<img>` carries no `image/*` data either — the image survives only as an `<img src="…">` URL
inside the `text/html` markup, never as bytes.

A Firefox **bare image** (an `<img>` grabbed directly, no text selected around it) is the sparsest case: only the two
Windows drag-cursor mimes arrive — no `text/html`, `text/plain`, or `image/*` — so the drop carries no usable image
data or URL through Qt at all.

A Firefox **link** (an in-page `<a>`) and the **address-bar URL** both expose the page URL plainly, via
`text/uri-list` (already the format §15.1's URL-drop rule reads) and
`application/x-qt-windows-mime;value="UniformResourceLocatorW"`, plus a synthesized `.url` Internet Shortcut file
under `application/x-qt-windows-mime;value="FileContents"`/`FileGroupDescriptor(W)`. In a controlled pair — the same
link dragged from the page, then its target loaded and the resulting address-bar URL dragged in turn — the link
carried `text/x-moz-url-desc` (the link's title text) and the `text/_moz_htmlcontext`/`text/_moz_htmlinfo` hints,
while the address-bar drag carried neither, having no page DOM behind it. An earlier, uncontrolled round of assorted
link drags was less consistent about the `text/_moz_htmlcontext`/`text/_moz_htmlinfo` pair, so treat that split as
indicative, not a hard rule.

So in Firefox a selection and a link/address-bar drop are mutually exclusive, not complementary: a selection never
carries its page's URL, and a link or address-bar drag never carries the surrounding page markup. §15.1's rule that a
selection drop hands its fragment to the scraper "with the page URL alongside, where the platform provides one" has
no source for that URL in Firefox — the platform can only ever hand over a *separate* link/address-bar drop, never
one drop carrying both.

**In Chrome and Edge** — identical on both, byte for byte, since Edge is Chromium underneath — the same four drags
were repeated on the same pages. Both write `text/x-moz-url` (URL and title, `\n`-joined) on their own link and
address-bar drags too, so that format is a shared de-facto convention, not a Firefox tell. Neither ever offers
`application/x-qt-windows-mime;value="HTML Format"`.

The material difference is `application/x-qt-windows-mime;value="chromium/x-renderer-taint"`: a short mime, present
on *every* Chromium drop tried — selection, image, and link alike — holding the source page's **origin**, scheme and
host only (`https://www.artstation.com`), never the full path. It is Chromium's only drop-carried hint of where a
selection or an image came from: coarse enough to route a drop to the right site's scraper, not precise enough to
refetch the exact page. It is absent from the address-bar drag, which has no source page to taint.

A Chromium **image** drag is richer than Firefox's: it carries the image's own URL directly, via `text/uri-list`,
`text/plain`, and `UniformResourceLocatorW`, plus the surrounding `<img>` markup (`src` and `data-src`) in
`text/html` — still no raw `image/*` bytes, and the `.url`-shortcut `FileContents` that a link drag populates comes
back empty here, since Chromium only synthesizes it for a navigable page, not an image URL.

So Chromium's selection and image drops are not fully silent about their source the way Firefox's are —
`chromium/x-renderer-taint` gives the origin, which §15.1's "page URL alongside" rule could route a scrape by, if not
fetch a specific page with. macOS and Linux are untested on any browser; a browser that exposes a Windows
`HTML Format` payload, or the full `SourceURL` some other way, would change this conclusion further.

A **multi-image lightbox** (ArtStation's product gallery, seven thumbnails plus an enlarged view) confirmed §15.1's
generic image rule needs no per-site help here: every thumbnail `<img>` carried `data-src` pointing at the full-size
original (`.../large/file.jpg`) alongside a 330×330 `src` (`.../medium/file.jpg`); the enlarged view's own `<img>`
already had `src` pointing straight at `/large/`. Preferring `data-src` over `src` — already §15.1's rule, no
ArtStation-specific rewrite invoked — pulled all seven originals (1800×1012, confirmed by downloading them), each a
self-contained CDN URL with its own path and no cross-thumbnail structure to key off. `data-src` for a lazy-loaded
image is a common web convention, not one this site invented.

This generalizes past ArtStation: a dropped selection or image can never be reliably attributed to a site at drop
time — Firefox gives no origin at all, and Chromium's `chromium/x-renderer-taint` gives only the bare origin, present
or absent per browser and drop shape, not a value anything should branch a scraper choice on. So the image-candidate
extraction that §15.1 already describes (`srcset`, `data-src`, `og:image`) has to be the *only* path for a
selection/image drop — never a fallback behind a "detect the site, run its rule" step, since that detection isn't
reliably available to fall back from. A site scraper's per-site thumbnail-to-full-size rewrite (§15.1's stated
exception) stays reserved for a site that has no `data-src`/`srcset` to read at all; it never substitutes for the
generic rule. The corollary: nothing about this drop-acquisition design should require a Chromium-family browser —
Firefox already has to work correctly with zero source-page hint, so Chrome/Edge's extra (and undocumented,
unversioned) `chromium/x-renderer-taint` hint is strictly an opportunistic bonus, not a dependency.

## §15.2 URL extraction: site scrapers, with an LLM fallback

[[[acquisition-tooling#url-extract]]]

The predecessors extracted a tutorial's fields with per-site scrapers — BeautifulSoup over a fetched or browser-rendered
page — and every one of them broke the day its site changed its markup. An earlier draft of this section replaced them
wholesale with a local LLM. The decision now runs the other way: **site scrapers are primary, and are the user's to
keep working**. The fields that matter — a title, the authors, a description with its images, a duration — sit in a
site's markup in places a few CSS selectors name exactly, and a scraper that breaks is a script the user edits that
afternoon rather than a model to re-prompt. The LLM stays, as the fallback for hosts nobody has written a scraper for
([[acquisition-tooling#llm-url-extract]]).

### §15.2.1 One method, one result shape

[[[acquisition-tooling#scraper-protocols]]]

Scraping is a **desktop concern** and lives in `rehuco-agent`: a productivity aid feeding the editor, not something a
node does unattended, so `rehuco-core` learns no HTTP client and no HTML parser. Two kinds of Protocol, both
structural, both plain classes:

- **`PageFetcher`** — `fetch(url) -> Page`, a `Page` being the URL asked for, the URL it resolved to, and the HTML. The
  default fetches over plain HTTP with a browser User-Agent. A **browser-driven fetcher**, Selenium on the persona
  ([[acquisition-tooling#browser-persona]]), is used instead whenever a scraper declares it needs one, or the user
  ticked **Use browser** for it on the Scrapers settings page — a per-scraper choice, since the heaviest dependency
  in the app should be paid for by the site that needs it, not switched on for every scrape at once. A fetcher raises
  `FetchError` on a failed fetch, or `LoginRequiredError` when the page it landed on is a login wall rather than the
  one it asked for — `HttpPageFetcher` raises the latter itself on a `401`/`403`, the one generic signal a plain HTTP
  fetch has; a scraper's own parsing raises it too, since only the scraper knows what its site's login wall looks
  like when the status is a plain `200`.
- **`SiteScraper`** — what every scraper is: `matches(url) -> bool`, a host or prefix test as tc4's `can_scrap` was, a
  `label`, the `publisher` it fills in, `site_name`/`site_url` — what the Scrapers table's link for this scraper
  shows and where it takes the user, opened through the persona browser's `open_for_login`, never Selenium
  ([[acquisition-tooling#browser-persona]]) — a `needs_browser` flag — `True` on a scraper that cannot read its site
  without a real browser session, always routed through the persona regardless of the table's ticks — and one
  method — `scrape_page(page) -> ScrapeResult`. **Not one Protocol per
  resource type**: an earlier draft dispatched to `scrape_tutorial`/`scrape_reference_images`/`scrape_collection`
  separately, one per plugin key ([[plugins#plugin-blocks]]), but a `ScrapeResult`'s fields are an unvalidated,
  plain mapping rather than pre-filtered to one type's declared set (below) — so there is nothing left for three
  near-identical methods to decide that one doesn't. A concrete scraper's `matches(url)` alone decides whether it
  runs; ArtStation selling tutorials and reference packs from the same product page returns whatever fields that
  page has, and the reader picks out what applies.

A `ScrapeResult` holds three things. **`fields`** is a plain mapping spelled from `SCRAPED_FIELD_NAMES`
([[field-schema#resource-types]], e.g. `"title"`, `"advertised_duration"`) — the part of the plugin field-name
vocabulary a web page can actually show, not restricted to any one type's declared set: a scraper returns
whatever it found, and picking out what fits the document a result is applied to happens where it is applied, not
at scrape time. Left out on purpose are what the app measures from the local files (`original_size`, `current_size`,
`original_duration`, `current_duration`, `current_count` — a page's own claim goes in `advertised_duration` /
`advertised_count` instead) and the user's own state (`hidden_images`, `extra_tags`, the boolean flags, `rating`,
`learning_paths`, the `.rehu` timestamps): a scraper converts the page it fetched, and none of those come from a
page. **`description`** is Markdown, with any images the scraper chooses to embed already rewritten to a stem-less
placeholder in encounter order (the `<stem>` of `<stem>NN` is a per-document fact no scraper knows). **`images`**
are the `(slot, url, referrer)` triples the image pipeline of
[[acquisition-tooling#drag-drop-aids]] downloads, substituting the real stem in. A scraper decides for itself whether
any of `images` are also referenced in `description` — ArtStation and Udemy download images without ever mentioning
them in the description text, while a scraper that embeds several of what it downloads directly into the description
is equally supported.

A result is a proposal. A field the scraper could not find is absent, never filled with a guess, and the editor shows
what arrived beside what was there.

A result is **validated as a whole** before anything is applied, against one checked-in JSON Schema, the
**scrape-result schema** (draft-07, checked with `fastjsonschema`). It is the JSON shape of the three parts above:
`{"fields": {...}, "description": str|null, "images": [{"slot", "url", "referrer"}]}`, with `description` and
`images` optional. `fields` accepts only a key in `SCRAPED_FIELD_NAMES` and no other, and each field's value must
pass the same type rules that lock a loaded document with a malformed field ([[data-model#write-integrity]]);
`level` is further held to its fixed value set ([[field-schema#field-types]]), and an integral float where an
integer belongs (`3600.0`, which JSON Schema's `integer` admits) is read as that integer rather than refused. A
result that fails is rejected entirely, and nothing from it is applied. The log names the scraper and the
location of the first error (`data.fields.authors[0].url`). Every result is checked, whether the scraper returned
a `ScrapeResult` **or its JSON-shaped mapping directly** — the two accepted return forms `SiteScraper.scrape_page`
may answer with — and the built-in scrapers are checked too. A scraper is user code, so what it returns is treated as
input from outside the app; the step that applies a result can then trust every value without checking it again.

An `authors` entry a scraper contributes is a plain name, or, when the site links the name to an author's own page, a
`{"name", "url"}` record ([[field-schema#authors]]) carrying that link — ArtStation's product page does this (#273),
and Udemy's instructor block does the same (#274). A scraper emits the record form whenever such a link is
present and falls back to the plain name only when the page has none; this is the one rule, stated here rather than
re-derived per scraper. The record's `url` must be an `http(s)` address, and the schema rejects any other.

### §15.2.2 Legacy `.tc` author-URL upgrade

[[[acquisition-tooling#legacy-author-url]]]

tc4 kept only the author's name; the sites both built-in scrapers cover always carried the profile link too, so it
was simply dropped on the floor. Nothing above changes for `.tc` migration ([[acquisition-tooling#tc-to-rehu]]):
a migrated document's `authors` stays name-only, since the source format never captured the URL to carry forward.

### §15.2.3 The registry, and the user's own scrapers

[[[acquisition-tooling#scraper-registry]]]

Scrapers are looked up in an **ordered list**, first `matches()` wins, and the list is the **user's scripts folder
first, then the built-ins** — so a user's module overrides a shipped scraper for the same host. That is the whole answer
to brittleness: when a site changes, the fix is a `.py` file in a folder, not a release. The folder is a settings page,
**Scrapers** ([[appendices.settings-pages#category-groups]]): the folder path; a table with **one row per scraper**,
built-ins included — naming it as a link (`site_name`, opening `site_url` in the persona browser on a click), its
source file (or "Built-in"), and a **Use browser** checkbox ([[acquisition-tooling#browser-persona]]) — plus one row
per file that loaded no scraper or failed to,
carrying the import error, since a scraper that silently did not load is indistinguishable from one that matched
nothing; and a **Reload** that re-scans the saved folder without a restart. A user's own script needs no import from
this package
at all: `SiteScraper` is a plain structural Protocol, so a copied-and-edited file satisfies it by shape alone, with
no registration step beyond being a `.py` file in the folder. Scripts in that folder are **trusted local code**, run
with the app's own privileges; the page says so and the app does nothing to sandbox them. Built-in scrapers ship for
**ArtStation** and **Udemy** first, the two the predecessors kept alive longest. A script author gets the schema
every result is validated against ([[acquisition-tooling#scraper-protocols]]) by running `rehuco-agent --scrape-schema PATH`,
which writes it to a file. It writes a file rather than printing because the packaged Windows build prints nothing
to a console ([[appendices.release-runbook#windows-console]]), and it is the same schema the installed app uses.
`rehuco-agent --scrape URL [--scrapers-folder DIR] [--output PATH]` runs the same lookup, fetch and parse from the
console: `--scrapers-folder` builds the registry over that folder for this call only, without touching the saved
Scrapers setting, so a script can be developed and tested end to end without opening the GUI; the result prints to
stdout, or to `--output PATH` when the packaged build's silent console makes that the only way to see it.

### §15.2.4 The browser fetcher and its persona

[[[acquisition-tooling#browser-persona]]]

The browser-driven fetcher launches a real browser through **Selenium** — a plain runtime dependency of
`rehuco-agent`, not an opt-in extra, so the packaged Windows/macOS builds carry it too. What stays optional is
having a **browser installed**: Selenium Manager, bundled in the wheel, resolves the matching driver for Firefox,
Chrome or Edge automatically on first use, and a fetch fails with a clear message naming the browser when neither
is present.

The browser runs on a **persona**: a profile directory of its own, one per browser, under
`<config>/rehuco-agent/persona/<browser>` — the app's own scraper identity, never the user's everyday browser, its
logins, or its history. It keeps cookies and local storage between runs, which is what lets it read a **paywalled or
members-only page**: the user logs in once, by hand, and every later scrape through that persona carries the
session, the way tutcatalogpy3's driver launched Firefox on a dedicated profile.

**Logging in and scraping are two different processes on the same profile, never one shared session.** A
WebDriver-controlled browser is flagged as automated by the browser itself for as long as the session runs, whatever
it happens to be doing at that moment — Firefox's Marionette sets `navigator.webdriver` the instant remote control
is enabled, not only while a command is in flight, because the WebDriver spec requires it. Google's and
Cloudflare-grade sign-in checks key off exactly that flag, so a Selenium-driven session cannot sign in anywhere
either of them guards, no matter how long the user is given to answer a challenge by hand, and no per-site workaround
changes that — it is what a WebDriver session *is*. **Open the browser** therefore never touches Selenium at all: it
launches the persona's browser directly, the same way double-clicking its icon would, so the browser Google or
Cloudflare sees is an ordinary one. What carries a login forward to a later, Selenium-driven scrape is not a shared
live session — it is the **profile directory** the two share: cookies a plain login window wrote are on disk before
that window ever closes, and any scrape opened later on the same folder reads them like any other returning visit.
The one thing the two cannot do is run at once: a profile can be held open by only one browser process at a time,
plain or Selenium-driven alike, so a scrape attempted while the login window is still open fails to start its own
session, with a message naming that as the likely cause. A scrape itself always starts a short-lived Selenium
session (headless unless **Show the browser while scraping** is ticked) and quits it when done — there is nothing
left running for a next scrape, or a login, to find.

Controls on the Scrapers page:

- **Browser** — Firefox, Chrome or Edge; which persona a scrape or a login uses.
- **Show the browser while scraping** — headless is the default; visible is how a page that came back empty is
  inspected.
- **Open the browser** — launches (or, if one is already open, brings forward) a plain, un-automated window on the
  persona, so the user can log in to any number of sites by hand and leave the window open or close it; either way
  the logins persist in the profile. This is also the remedy when a session has expired, so it stays one click away
  rather than buried in a first-run flow.
- **Reset persona…** — closes any open login window and deletes the persona folder, for a clean, logged-out profile
  the next use recreates from scratch. Confirmed first, since it logs the persona out of every site at once.
- **Use browser**, one checkbox per row of the Scrapers table ([[acquisition-tooling#scraper-registry]]) — the
  per-scraper opt-in described above. A `needs_browser` scraper's box is shown checked and disabled: that choice is
  the scraper's, not the user's, to make.

**No stealth driver, and none would help sign-in anyway.** tutcatalogpy3 used `undetected-chromedriver` to defeat
per-page anti-bot detection; this build does not. It is GPLv3 (this project is MIT), its last release predates this
work by over a year, and it bypasses Selenium Manager's own driver resolution with its own. It also would not have
solved the sign-in problem above regardless: `navigator.webdriver` is set by the WebDriver spec itself, not by a
particular driver's fingerprint, so no amount of patching a *scraping* session makes it eligible to sign in anywhere
Google- or Cloudflare-grade detection watches for that flag — only the plain, unautomated login window is. A scrape
that still gets challenged on an ordinary content page (rarer, since such gates are usually placed on sign-in and
similar flows rather than on every authenticated page view) is its own, later issue if it turns out to matter.

**Detecting a login wall** is the scraper's job, not the fetcher's: most sites answer one with a plain `200` and a
login form rather than a distinguishing status code, so only a scraper's own parsing — noticing the element it
wants is missing, and the site's login marker is present — can raise `LoginRequiredError`
([[acquisition-tooling#scraper-protocols]]) with any reliability. The one generic fallback is a `401`/`403` over
plain HTTP, which `HttpPageFetcher` itself turns into the same error. Either path becomes a `LoginRequiredScrapeError`
naming the scraper and the host, shown as the drop's banner row the same way every other scrape failure is.

The profile is a **credential store**: it lives only under the config directory, is never inside a resource folder,
and is never synced or copied by anything the app does. Sessions expire and two-factor sites re-ask; the app does
not try to keep a login alive, it only keeps the door to renewing one open.

### §15.2.5 The scrape runs on its own pool, not the app-wide task queue

[[[acquisition-tooling#scrape-job]]]

A drop submits one `ScrapeJob` to a small, dedicated `ScraperExecutor` — **not** the app-wide task queue
([[appendices.task-queue]]). That queue is a single worker running one job at a time, right for a checksum sweep or a
catalog import measured in hours, wrong for an interactive fetch a sweep must never delay: a scrape dropped while one
is running gets a free worker immediately, and two scrapes dropped close together run concurrently rather than
serializing behind each other. A scrape is submitted under the document's log scope, so its fetch and its parse are
readable in that document's log alongside the app-wide one ([[appendices.logging#scopes]]) — the one piece of the
task queue's machinery still needed, since a pool thread otherwise inherits no context from whoever submitted the
work to it. Not a `TaskJob`: with no pause/resume/cancel worth the machinery for one fetch-and-parse, a scrape has no
row on the Tasks dock. Its trace is its log lines, plus one banner row on the document while it runs — the same
message-only inline strip every other condition already uses — and, if it did not succeed, one more naming why: the
no-scraper-matched host, worded exactly as `rehuco-agent --scrape URL` prints it
([[acquisition-tooling#scraper-registry]]), or the scraper's own failure. Its result is applied on the GUI thread,
and only if the document is still open at the same path; a document closed or renamed while its page was being
fetched simply discards the result. `markdownify`, `beautifulsoup4`, `requests` and `selenium` are all plain runtime
dependencies of `rehuco-agent` ([[acquisition-tooling#browser-persona]] for why Selenium is not an opt-in extra).

### §15.2.6 The LLM fallback, deferred

[[[acquisition-tooling#llm-url-extract]]]

For a host no scraper matches, the earlier design still stands — as a fallback, and still deferred: fetch the page text
and hand it to a small local model for **structured extraction into the scrape-result schema**
([[acquisition-tooling#scraper-protocols]]), the same typed result a scraper returns, with no per-site code at all.

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
- **The harder half is fetching/rendering, not extraction.** JS-heavy course pages (Gumroad; Udemy's renders
  server-side, #274) may still need a headless browser to render before extraction, and a readability/main-content
  trim before the model keeps quality up on long pages. So per-site effort drops a lot but doesn't vanish — it moves
  from "parse this site's DOM" (brittle) to "render and trim this site's page" (more robust).
- Implemented on the same `ScraperExecutor` pool a scraper runs on ([[acquisition-tooling#scrape-job]]), not the
  app-wide task queue ([[architecture-design#components]]).

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

A conversion never backs a screenshot up to an `.orig` of its own — a rename is not a write, so nothing is lost by it,
and the only backup a conversion produces is `info.tc.orig`, kept for reference; an image acquisition reusing an
occupied slot is the one writer that does back a screenshot up ([[acquisition-tooling#drag-drop-aids]]). This is the
**first concrete use of the read/import upgrade path ([[data-model#schema-version]])** rather than a one-off script —
though a `.tc` is *not* itself "format v0": it is a different file format that never carried a `.rehu` version to
upgrade from, so the adapter reads one and emits the **current** `.rehu` layout, stamp included (v0 means an *unstamped*
`.rehu`, [[data-model#schema-version]]). Checksum generate/verify ([[data-model#checksums]]) belongs alongside the
migration action in the same tooling.

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
do — the mirror of Convert's own visible-while-`legacy_tc` rule: **Discard is offered while any `.orig` backup is
present** — `info.tc.orig`, or a screenshot an image acquisition backed up before reusing its slot
([[acquisition-tooling#drag-drop-aids]]). A save never discards it on its own — discarding is deliberate and confirmed
or it is not discarding at all, and the `.orig` pair is the only copy of the original `.tc` (and, once retired, of the
legacy manifest).

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
