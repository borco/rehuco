# Diagrams

Exploratory diagrams of how rehuco-agent actually works today, read straight off the code
(`packages/rehuco-agent/src/rehuco_agent/`).

| Diagram | UML kind | What it shows |
| --- | --- | --- |
| [activity-open-document.md](activity-open-document.md) | Activity | The same "open a path" flow as a decision/branch diagram, closer to how you'd narrate the control flow out loud. |
| [component-decomposition.md](component-decomposition.md) | Component | The containment hierarchy from `Application` down to one field's widgets. |
| [sequence-open-document.md](sequence-open-document.md) | Sequence | What happens end-to-end when a `.rehu` path is opened, both as the primary instance and as a forwarding secondary ([[nodes#single-instance]]). |

> [!NOTE]
> Each diagram carries a `[[doc#slug]]` declaration
> ([[readme#symbolic-cross-references]]) and is cross-referenced from [[plugins#dock-shell]] /
> [[plugins#viewer-editor-both]], so `tools/check_slug_refs.py` catches a broken link either
> direction. Listed in `mkdocs.yml`'s nav under Design Specs (a "Diagrams" section, above
> Appendices) -- but still absent from the `docs/specs/README.md` document map's numbered table,
> since this is a scratch space for understanding the system, not a numbered spec section.
>
> Rendered via `mkdocs-puml`, which turns each ` ```plantuml ` fence into an inline light/dark-themed
> SVG at `mkdocs build` time (`puml_keyword: plantuml` in `mkdocs.yml` so the plain `plantuml` fence
> matches without renaming) -- so the published site has no runtime rendering dependency at all.
> `PUML_URL` picks the PlantUML server: unset locally (`make docs-serve`), so it falls back to the
> public `https://www.plantuml.com/plantuml`; `publish-docs.yml` points it at a self-hosted
> `plantuml/plantuml-server` `services:` container instead, so the deploy doesn't depend on the
> public server's availability. (An earlier attempt used `mkdocs-kroki-plugin`, dropped after
> discovering it hard-depends on `properdocs`, a package that hijacks `mkdocs build` output to push
> users toward a fork of MkDocs -- not something this project's dependency tree should carry.)
>
> Diagrams are rendered small inline; click one to open it full-size in a new tab
> (`docs/javascripts/diagram-open.js` serializes the `<svg>` to a Blob URL, so the browser's native
> image viewer -- zoom, right-click "Save image as" -- applies there, which it doesn't for an inline
> `<svg>` embedded in a page).
