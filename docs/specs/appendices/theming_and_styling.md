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
- **`themed_svg_icon`/`themed_glyph_icon`/`ThemedIcons`** (`themed_icons.py`) — the app-wide cache of
  themed icons, one shared `QIcon` per source SVG (or glyph) and variant, parented to the
  `QApplication`. Its `PaletteSvgIconEngine` reads `QApplication.palette()` **as it paints** rather
  than storing a color, memoizing renderers against the palette's `cacheKey` so a repaint under an
  unchanged palette costs a dict lookup. Nothing has to be rebuilt or notified for a glyph to follow a
  theme switch, and two windows showing the same action cannot disagree about it (see
  [[appendices.theming_and_styling#resolve-on-paint]]).
- **`CheckedToolButtonChrome`** (`checked_chrome.py`) + **`contrast.py`** — what a checked toolbar
  button is actually filled with, measured by rendering a probe and sampling it, and the choice of a
  glyph color that reads against it. Same technique, and the same reasoning, as the menu-row
  measurement in `RehuDocumentMenuEntry.row_style` (see
  [[appendices.theming_and_styling#checked-chrome-is-not-highlight]]).
- **`ApplicationPaletteChangeNotifier`** — one shared, application-wide event filter (created once
  per `QApplication` via `for_application`) that re-exposes `QEvent.Type.ApplicationPaletteChange`
  as a plain `palette_changed` signal. Replaces `QApplication.paletteChanged` (deprecated since Qt
  6.0). Qt fires that event several times for a single theme switch (four on Windows, all with the
  identical new palette), so the notifier coalesces by `QPalette.cacheKey` and emits once per real
  change — matching the old signal's once-per-switch. A single shared filter also lets any number of
  listeners subscribe without each installing its own (which would make every event in the app
  `O(listeners)`). Themed icons are **not** among those listeners any more; what is left are the
  things that genuinely have to act on a switch rather than merely look different afterwards — QtAds'
  stylesheet pinning ([[appendices.qt-ads#stylesheet-reload]]), `MarkdownEdit`, `TypeBadge`.
- **`ActionIconThemeHandler`** / **`GlyphActionIconThemeHandler`** — give one `QAction` the shared
  themed icon (SVG- or glyph-backed, respectively) built from a source path. Thin by design: the icon
  they assign colors itself, so neither holds a color, subscribes to anything, or has anything to
  rebuild. `ActionIconThemeHandler` additionally wires an optional menu `companion`, which is the only
  reason an object is needed at all. Its `flat` parameter skips the checked-state color for an action
  living in a menu row, which paints no filled chrome behind its icon the way a toolbar's checked
  button does — the row's own native checkmark communicates checked-ness there instead.
- **`ThemeModel`** — the single source of truth for the app's theme *mode*
  (`Qt.ColorScheme.Unknown`/`Light`/`Dark`), deliberately kept distinct from
  `QApplication.styleHints().colorScheme()` itself: that property reports the *resolved*
  appearance, and Qt resolves `Unknown` to whatever the OS actually is the moment it's queried —
  it never echoes `Unknown` back. Reading it as "the current mode" cannot tell "explicitly Light"
  apart from "Unknown, currently resolving to Light because the OS is in light mode", which breaks
  any control cycling or checking against it (#57). Every mode-driven view reads/writes
  `ThemeModel.mode` and listens to `mode_changed` instead — never `QStyleHints.colorSchemeChanged`
  directly.
- **`ThemeManager`** — cycles a toolbar action through a shared `ThemeModel`'s follow-system/
  light/dark mode on each click, reflecting the current mode on the action's icon.
- **`ThemeMenu`** — builds and owns three checkable actions (`default_action`/`light_action`/
  `dark_action`, e.g. for a `View` menu's theme entries — their text/meaning has no legitimate
  per-caller variation, so the class builds them itself rather than taking them as parameters,
  the same way `DockableDialog` builds its own `toggle_action`) and wires them to a shared
  `ThemeModel`, exclusive via a `QActionGroup` so exactly one is checked at a time, matching the
  model's mode exactly (including the follow-system entry) rather than a resolved scheme. Placing
  the three actions in an actual menu is the caller's job. `ThemeManager` and `ThemeMenu` are
  independent of one another — each usable on its own — but both read/write the same `ThemeModel`,
  so picking a mode in either one shows up in the other.
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

## 2. A themed glyph's color is resolved as it paints, never stored

[[[appendices.theming_and_styling#resolve-on-paint]]]

**Symptom** (#304): with several `.rehu` documents restored from the session, switching the theme
recolored only the document that had been focused on restart. Every other one kept the previous
theme's glyphs for the rest of the run — black on dark, or washed-out white on light after the reverse
switch. A document opened from the menu *after* the switch was always correct. Same actions, same
code, same application instance.

**What it was not.** Five explanations were measured and eliminated before the design changed: a dark
`HighlightedText` (it is `#ffffff` in both themes); un-recolorable SVG sources (21 icons have drawing
elements with no `style` attribute, but the root `<svg style>` takes the fill and they inherit it);
garbage collection of the fire-and-forget handlers (they stay parented to their action and survive a
forced collection, tested with the action's own wrapper discarded too); merely-disabled actions; and
`QtAdsFocusTracker` treating the focused dock differently (its stylesheet reaches only tab chrome).

**Root cause, structurally.** Every themed icon was a *cached color* that some object had to keep up
to date. `MainWindow` restored the session before constructing `ThemeModel` — and constructing that is
what applies the saved theme — so every restored document's icons were necessarily built against a
palette about to be replaced, and became correct only by surviving one `palette_changed` round-trip
across the tens of handlers an open document creates. The precise reason a subset stopped being
notified was never pinned down, and deliberately so: the fix deletes the state the failure depended on
rather than repairing one path to it.

**Resolution:** `PaletteSvgIconEngine` reads the palette at paint time, and `ThemedIcons` hands every
action asking for the same source SVG the same `QIcon`. A glyph's color stops being something kept up
to date and becomes something computed when it is needed, so an unsubscribed handler, a
built-before-the-theme-was-applied document and a missed repaint all produce the right color anyway.
The startup ordering was corrected as well — the theme is applied before the session is restored — not
as the fix, but so a real fragility stops being load-bearing.

## 3. A checked tool button is not filled with `Highlight`

[[[appendices.theming_and_styling#checked-chrome-is-not-highlight]]]

**Symptom:** a checked toolbar toggle's glyph sat near-invisibly on its own button — white on pale
blue under the Windows 11 dark theme, and white on near-white under `Fusion`'s light one.

**Root cause:** the checked glyph was colored from `HighlightedText`, on the assumption that the
chrome paints a `Highlight`-colored backdrop behind it. Measured, no style does:

| style / theme | fill actually painted | text the style draws on it |
| --- | --- | --- |
| `windows11` light | `#0067c0` (`Accent`) | `#ffffff` |
| `windows11` dark | `#4cc2ff` (`Accent`, *pale*) | `#000000` |
| `Fusion` light | `#dcdcdc` (a shade of `Button`) | `#000000` |
| `Fusion` dark | `#414141` | `#ffffff` |

`Highlight` is `#0067c0`/`#0078d4` and is not what any of them fills with; `HighlightedText` is
`#ffffff` in *both* Windows 11 themes, so it can never produce the black Qt itself uses on `#4cc2ff`.

This is also why the staleness in
[[appendices.theming_and_styling#resolve-on-paint]] hid so well. A checked glyph was `#ffffff`
whatever the theme, so a toolbar frozen in the wrong theme still looked right wherever a dock happened
to be open — which is exactly the "not all of them, most are correct in the same toolbar" the defect
was first reported as.

**Resolution:** `CheckedToolButtonChrome` renders a probe button into a small image, samples its
center, and `contrast.py` picks the first of `HighlightedText`, `ButtonText` on the opposite side of
the brightness midpoint, falling back to black or white when neither is. That reproduces, in all four
cases above, the color the style draws its own button text in. Perceived brightness rather than
`lightness()`, for the reason `RehuDocumentMenuEntry.row_style` already records: a saturated mid blue
reads far darker than its max/min average suggests. Enabled and disabled are measured separately,
since a disabled checked button is filled with a neutral shade rather than the accent.
