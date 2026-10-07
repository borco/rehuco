# TutCatalog5

<https://gitlab.com/iborco-software/tutcatalog/tutcatalog5>

A full Python/Qt6 rewrite (2024–2025) built around a **typed field toolkit** — a TOML-driven type system with
editor/viewer widget pairs for every field kind.

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

Rendered and edited `.tc` through a config-declared field/type system rather than a hard-coded viewer.

## Feature ledger

| Feature | TutCatalog5 | rehuco |
| --- | --- | --- |
| User-editable configuration of fields and pages: `defaults.toml` declares each field (type, key, label, groups, completions) and, per resource type, the editor tabs and viewer pages as ordered field lists with separators. A user points the app at their own file; a new `[[fields]]` entry is stored in the `.tc` | Yes (not resource-hub, which has fixed fields) | **TBD.** The spec has the idea as *declarative types* — a type that is only a field list over the toolkit ([[plugins#core-vs-plugin]]) — but nothing lets a user declare fields or lay out pages, and no issue exists |
| Typed field toolkit (editor/viewer pairs) | TOML-driven | Built — one class per field kind; a type's plugin declares its fields |
| `.tc` view / edit | Yes | Built — `.rehu`; `.tc` read and converted |
| YAML sidecar | Yes | Read for conversion only |
| TOML sidecar | Yes | **Not planned** — not read |
| Tutorial / ReferenceImages / Collections types | Yes | Built, except Collections' fields — see [TutCatalog4](tutcatalog4.md) |

## Importing its data

The YAML `.tc` converts as in [TutCatalog4](tutcatalog4.md). The TOML variant is not read. Its field names
(`authors`, `extra_tags`, `images_count = {declared, actual, is_complete}`, `urls`) match rehuco's target shape except
`images_count`, which becomes a scanned integer.
