# Theming and Styling

[[[appendices.theming_and_styling]]]

## Overview

[[[appendices.theming_and_styling#overview]]]

`borco_pyside.theming` ([[plugins#field-toolkit]]) holds the app's palette-aware icon rendering:

- **`recolored_svg_icon`/`RecoloredSvgIconEngine`** (`svg_recolor.py`) — a monochrome SVG asset
  recolored to a given `QColor` and rendered fresh at whatever exact size Qt requests, via a custom
  `QIconEngine` rather than a fixed-resolution baked pixmap.
- **`glyph_icon`/`GlyphIconEngine`** (`glyph_icon.py`) — the same "render fresh, no fixed-resolution
  cache" approach for a single icon-font glyph (e.g. Phosphor) instead of an SVG; both share the
  `pixmap()` plumbing via `theming/utils.py`'s `painted_pixmap`.
- **`ActionIconThemeHandler`** / **`GlyphActionIconThemeHandler`** — keep one `QAction`'s icon
  (SVG- or glyph-backed, respectively) rebuilt in the current palette's colors on every
  `QApplication.paletteChanged`.
- **`ThemeManager`** — cycles an action through follow-system/light/dark (`Qt.ColorScheme`).
- **`LineEditClearActionFilter`** (`borco_pyside.widgets`) — an app-wide consumer: installs a themed,
  glyph-rendered clear action on every `QLineEdit`, including ones this app never constructs
  directly ([[plugins#field-toolkit]]'s field toolkit line edits, and any `.ui`-file-generated one).

## 1. Phosphor's "Duotone" weight cannot be used as a font

[[[appendices.theming_and_styling#duotone-font-limitation]]]

**Symptom:** rendering any glyph through `Phosphor-Duotone.ttf` via `glyph_icon` produced a flat,
fully-opaque shape — no lighter secondary region, regardless of which color was passed. One
specific codepoint (the calendar glyph, `\uE108`, used correctly by every other Phosphor weight)
rendered as a bare, unrecognizable solid bar rather than a calendar shape at all.

**Investigation:**

- Confirmed `Phosphor-Duotone.ttf` is **not** an OpenType color font: a raw byte search of the file
  found no `COLR`/`CPAL`/`SVG `/`CBDT`/`sbix` table tag, only the plain outline `glyf` table every
  other Phosphor weight uses. There is no embedded per-region alpha/color data a renderer could pick
  up in the first place.
- Rendered several codepoints through the Duotone family directly: the star glyph (`\uE46A`)
  produced a complete, correctly-shaped star — solid, single-color, no partial transparency anywhere
  in it. The calendar glyph (`\uE108`, otherwise identical across weights) produced only a plain bar.
  The two results are inconsistent with each other, suggesting the bundled Duotone `.ttf`'s
  per-glyph coverage is itself incomplete, not just monochrome.

**Root cause** (confirmed against Phosphor's own project docs, not just inferred): duotone rendering
is **not implemented in the font files at all**. Phosphor's own README states it plainly — *"The
duotone weight is not yet available for font implementations, as fonts do not support baked-in
alpha/opacity. In future there are plans to move to an SVG-based approach with full support for all
icon weights."* Their web package achieves the two-opacity look via a CSS `:after` pseudo-element
layer at a fixed low opacity; their Flutter package achieves it by stacking two widgets. Neither
mechanism has anything to do with the `.ttf` file itself — a single glyph painted with one solid pen
color (what any plain text-rendering call, including `GlyphIconEngine.paint`, does) fundamentally
cannot reproduce it, independent of which codepoint is chosen.

**Resolution:** `Phosphor-Duotone.ttf` was removed from `design/fonts/` and from every consumer
(`main.qrc`'s font resources, `app.py`'s `ICON_FONT_RESOURCES`) — it cannot serve the purpose it was
added for. If a genuine duotone look is wanted for some icon later, it needs a real two-layer
source: Phosphor's SVG assets, recolored per layer and composited via the existing
`recolored_svg_icon`/`RecoloredSvgIconEngine` pipeline (already used for the app's own brand icon),
not the icon font.
