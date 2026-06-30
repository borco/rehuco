# §15. Acquisition and Migration Tooling

These features don't belong to the core data/swarm architecture, but they're what makes the catalog *populatable and maintainable* at scale (thousands of tutorials), so they matter for day-to-day usability. All are productivity aids feeding the editor the user reviews — assistive, not unattended.

## §15.1 Three drag-and-drop input aids (restored from TutCatalog4)

- **HTML selection → Markdown into the description editor.** Selecting content on a web page and dropping it on the description editor: the drop's `text/html` payload is converted to Markdown by a deterministic library (html2text-style) and inserted at the cursor. No LLM, no per-site logic, no fetching — it just transforms whatever HTML the browser handed over (with a sanitize/clean pass first, since pasted web HTML is messy). The cheapest and lowest-maintenance of the three; restore it early.
- **Image drag → download, rescale, auto-name screenshot.** Dragging an image from a browser onto a designated widget: download it, rescale to ≤300px wide (Pillow), and save as the next unused `imageXX` screenshot name. No LLM. Pairs with the screenshot-name normalization in migration (§15.3).
- **URL drop → extract tutorial info.** Dropping a URL: fetch/render the page and extract `{title, author, publisher, duration, description, …}` into the resource's fields. See §15.2 — this is the one with real nuance.

## §15.2 URL extraction via a local small LLM

The TutCatalog4 approach (geckodriver + BeautifulSoup + hand-maintained per-site scrapers) broke constantly because each site needed bespoke parsing logic kept up to date by hand. The modern approach removes that maintenance burden: fetch the page text and hand it to a model for **structured extraction into a fixed JSON schema**, eliminating per-site parsing code.

- **Local model is the right call** — zero per-call cost (run thousands of times across the catalog), no external dependency, offline, private. This is high-volume personal productivity, where a small local model beats a cloud API on every axis except peak quality, and extraction doesn't need peak quality.
- **Hardware fit:** a 7–8B model at 4-bit quantization (e.g. Qwen2.5-7B-Instruct) runs comfortably on the RTX 4070 (12 GB, fast) and on the Mac mini M1 (16 GB unified, slower but usable). Worth testing whether a 3–4B (Qwen2.5-3B) suffices for even more speed; reserve 14B (4070 only) for if 7B visibly struggles. Dispatch this to a capable node (4070 box or Mac mini), explicitly **not** the QNAP (§9.7/§9.12).
- **Reliability comes from constraining output, not from model size.** Use **grammar/JSON-schema-constrained decoding** (llama.cpp GBNF, Ollama format, Outlines, LM Format Enforcer) so the model *cannot* emit invalid structure or extra fields — this removes the entire "formatting" failure class and leaves only "did it find the right value," which small models do well. Pair with an explicit **"return null when a field isn't present"** instruction so the model leaves blanks rather than hallucinating a plausible-but-wrong value. With both, a constrained 7B is "right on common cases, never confidently wrong" — exactly the bar for an assistive tool the user reviews before saving.
- **The harder half is fetching/rendering, not extraction.** JS-heavy course pages (Udemy, Gumroad) may still need a headless browser to render before extraction, and a readability/main-content trim before the model keeps quality up on long pages. So per-site effort drops a lot but doesn't vanish — it moves from "parse this site's DOM" (brittle) to "render and trim this site's page" (more robust).
- Implemented as a **task-queue job** (§3), like other heavy work.

## §15.3 Migration: `.tc` → `.rehu` as format-version 0

Opening an old `.tc` file offers migration actions: convert `.tc` (YAML) → `.rehu` (JSON), and normalize the non-uniform screenshot names into the uniform `imageXX` scheme. This is the **first concrete instance of the format-versioning mechanism (§4.10)** rather than a one-off script: `.tc` is simply "format version 0," and migration is the upgrade-on-read/import rule applied to the oldest format. Checksum generate/verify (§4.5) belongs alongside the migration actions in the same tooling.

## §15.4 Deferral

Per the user's stated priorities, the acquisition aids (especially §15.2's LLM extraction) are **deferred until after the tutorial web viewer is working** — manual entry suffices in the interim. The HTML→Markdown and image-drag aids (§15.1) are cheap enough to restore earlier if convenient, but none of §15 blocks the core local-viewer / tablet-watching milestones.
