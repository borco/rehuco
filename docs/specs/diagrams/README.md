# Diagrams

Exploratory diagrams of how rehuco-agent actually works today, read straight off the code
(`apps/rehuco-agent/src/rehuco_agent/`). Each diagram carries a `[[doc#slug]]` declaration
([[readme#symbolic-cross-references]]) and is cross-referenced from [[plugins#dock-shell]] /
[[plugins#viewer-editor-both]], so `tools/check_slug_refs.py` catches a broken link either
direction. Still not wired into the `mkdocs.yml` nav or the `docs/specs/README.md` document
map's numbered table, though -- this is a scratch space for understanding the system, not a
numbered spec section.

All diagrams are PlantUML. Mermaid was tried first (each diagram had a parallel Mermaid version),
but dropped in favor of PlantUML-only after a side-by-side look -- Mermaid's rendering was judged
worse, and PlantUML has native support for diagram kinds (use case, activity) that Mermaid has to
approximate with a different diagram type.

Rendering note: PlantUML fences (` ```plantuml `) don't render on GitHub or in the built docs site
out of the box. Locally, use the VSCode "PlantUML" extension (`jebbs.plantuml`) configured with
`plantuml.render: PlantUMLServer` against the public `https://www.plantuml.com/plantuml` server (no
Java needed). This is a local-preview setting only -- it does not affect `mkdocs gh-deploy` in CI.

**Deferred (do after the current A2 code work):** wire PlantUML rendering into the published docs
site itself, via a `markdown-plantuml-plugin`/`mkdocs-kroki-plugin` `mkdocs.yml` config pointed at
a self-hosted `plantuml/plantuml-server` Docker image run as a GitHub Actions `services:` container
in `publish-docs.yml` -- avoids depending on the public server's availability/rate limits for every
docs deploy.

| Diagram | UML kind | What it shows |
| --- | --- | --- |
| [activity-open-document.md](activity-open-document.md) | Activity | The same "open a path" flow as a decision/branch diagram, closer to how you'd narrate the control flow out loud. |
| [component-decomposition.md](component-decomposition.md) | Component | The containment hierarchy from `Application` down to one field's widgets. |
| [sequence-open-document.md](sequence-open-document.md) | Sequence | What happens end-to-end when a `.rehu` path is opened, both as the primary instance and as a forwarding secondary ([[nodes#single-instance]]). |
