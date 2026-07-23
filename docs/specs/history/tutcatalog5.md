# TutCatalog5

<https://gitlab.com/iborco-software/tutcatalog/tutcatalog5>

A full Python/Qt6 rewrite (2024–2025) that went deep on a **typed field toolkit** — a TOML-driven
type system with editor/viewer widget pairs for every field kind. It is the cautionary tale the
[implementation plan](../implementation-plan.md) reacts to explicitly: it "built layers deeply …
without reaching a usable end-to-end whole," which is exactly why rehuco opens each milestone with a
tracer bullet instead. Its field-toolkit code is still a valuable **design** reference for slice A2.

## File formats

- **`.tc`** — per-collection sidecar, now readable as **both YAML and TOML** (the test corpus carries
  `collection_yaml.tc` and `collection_toml.tc` side by side). The TOML form also modernizes field
  names (`authors`, `extra_tags`, `images_count = {declared, actual, is_complete}`, `urls`).
- **`type`** still selects the resource kind — Tutorial / ReferenceImages / Collections (the README
  frames a "collection" as tutorial, images, etc.).
- **Config** — TOML-leaning app settings.
- Uses **[pyside-ibo](pyside-ibo.md)** as a submodule — specifically the **first** snapshot (the one
  since renamed `pyside-ibo-obsolete`), which supplied the image browser, Markdown editor/viewer,
  the generic widget set, `QSettings` helpers and the logging stack. Note it predates that library's
  `ApplicationSingleton`, which only exists in the later snapshot Resource Hub uses.

## What it did

Rendered and edited `.tc` through a general, config-declared field/type system rather than a
hard-coded viewer — the most ambitious editor of the lineage. But it stalled before becoming a
usable end-to-end catalog, its energy spent on the toolkit rather than a working spine.

## Compared with rehuco

| Capability | TutCatalog5 | rehuco |
| --- | --- | --- |
| Typed field toolkit (editor/viewer pairs) | Yes (TOML-driven) | A2 — tc5 is the design reference |
| `.tc` view / edit | Yes | A1 / A2 |
| YAML **and** TOML sidecars | Yes | rehuco standardizes on JSON `.rehu`; reads legacy `.tc` (YAML) via adapter (A3) |
| Reached usable end-to-end | **No** (the cautionary case) | Tracer-bullet-first methodology exists to avoid exactly this |
| SQLite cache / browser | Not really | `.rehudb` (B3) / browsers (B4) |
| Scraping, web, borrow, multi-node | No | deferred past D / Milestones C, D |
| `ApplicationSingleton` etc. | via pyside-ibo | reimplemented in `borco-core`/`borco-pyside` |

## Can rehuco work for its `.tc`?

**Yes.** The YAML `.tc` maps through the standard [field-schema](../field-schema.md) `.tc`→`.rehu`
adapter (A3). The **TOML** variant is tc5-specific and rehuco does not read TOML sidecars, but its
richer field names (`authors`, `extra_tags`, structured `images_count`) actually *pre-echo* rehuco's
own target shape — where they differ, rehuco's schema is the more considered version (e.g. the
structured `images_count` becomes a scanned integer). Nothing blocks import; tc5's lasting value is
the toolkit design, not its data.
