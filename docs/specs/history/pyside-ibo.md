# pyside-ibo

<https://gitlab.com/iborco-software/python/pyside-ibo>

<https://gitlab.com/iborco-software/python/pyside-ibo-obsolete>

Not an application but the shared **PySide6 utility library** the last two predecessors consumed as a
git submodule — "common classes and widgets for PySide6 projects." It exists in **two generations
that share a name**, which is the single most important thing to know about it: TutCatalog5 used the
first, Resource Hub used a ground-up second, and telling them apart is not as easy as it should be.

## The two snapshots — and the trap

| | pyside-ibo-obsolete (1st) | pyside-ibo (2nd) |
| --- | --- | --- |
| Period | 2025/05/07 – 2025/05/31 | 2026/05/04 – 2026/06/04 |
| Commits | 108 | 96 |
| Consumed by | [TutCatalog5](tutcatalog5.md) | [Resource Hub](resource-hub.md) |
| Declares | `name = "pyside-ibo"`, `version = "0.1.0"` | `name = "pyside-ibo"`, `version = "0.1.0"` |

> [!WARNING]
> **They are two different libraries wearing the same name.** The first repo was renamed to
> `pyside-ibo-obsolete` when the second was started fresh under the original name — so *both*
> projects' `.gitmodules` point at the **identical URL**
> (`git@gitlab.com:iborco-software/python/pyside-ibo.git`), and both `pyproject.toml`s declare the
> same package name *and* version. Neither the URL, the name, nor the version distinguishes them.
> **Only the pinned submodule commit does:**
>
> - TutCatalog5 pins `7a82b82` — a commit that exists **only** in `pyside-ibo-obsolete`.
> - Resource Hub pins `86f0085` — a commit that exists **only** in `pyside-ibo`.
>
> Don't reason about "what pyside-ibo does" without first resolving *which* one.

## What each contains

The second is not an evolution of the first — it is a **narrower rewrite**. It dropped the entire UI
surface (image browser, Markdown widgets, the generic widget set) and added the application-singleton
and property machinery instead:

| Module | obsolete (1st) | pyside-ibo (2nd) |
| --- | --- | --- |
| `core/application_singleton` | — | ✅ |
| `core/properties` (`SimpleProperty`, `ObjectProperty`) | — | ✅ |
| `core/datetime`, `core/exceptions` | — | ✅ |
| `core/connection_list` | ✅ | ✅ |
| `core/settings`, `core/path_mixin`, `core/unique_keys_enum` | ✅ | — |
| `logging/` — full GUI stack: `LogWidgetBridge` + model/filter/view/delegates + widget (~750–850 LOC) | ✅ (`log_widget_mixin`) | ✅ (`log_window`) |
| `sys/windows/registry` | ✅ | ✅ |
| `sys/windows/utils`, `constants.py` | ✅ | — |
| `image_browser/` (model/view/delegate/single-view) | ✅ | — |
| `markdown/` (editor, viewer, utils) | ✅ | — |
| `widgets/` (flow_layout, line_edit, path_edit, hidden_tool_button, single_selection) | ✅ | — |

## Formats and external state

Being a library it owns no document format. What it *touches*:

- **`QSettings`** app state (the first snapshot's `core/settings.py`).
- **Windows registry** (`sys/windows/registry.py`) — file-extension, context-menu and open-with
  registration; the Windows half of rehuco's file-association work.

## Compared with rehuco

rehuco depends on **neither** snapshot. The standing decision is that pyside-ibo is **reference-only**
and its utilities are reimplemented under rehuco's own conventions in `borco-core` / `borco-pyside`
(which are themselves slated to move out to their own repository). Current correspondence:

| pyside-ibo capability | rehuco |
| --- | --- |
| `ApplicationSingleton` (`other_instance_run = Signal(list)`, `setup(port, secret) -> bool`) | Reimplemented in `borco_pyside/core/application_singleton.py` — pure PySide6 (QLocalServer/QLocalSocket), no third-party singleton dep |
| `SimpleProperty` / `ObjectProperty` | `borco_pyside/core/properties.py` — `SimpleProperty` keeps the name; `TypedProperty` replaces `ObjectProperty` |
| Windows registry helpers | `borco_core/platforms/windows/` — `file_association`, `hkcu_registry`, `file_extension_context_menu`, `directory_context_menu`; exercised by the file-association pre-work spike (LocalEdit1 depends on it) |
| **In-app logging stack** (bridge + log widget) | **Carried, reworked** — `borco_pyside/logging/` has the bridge, the models, the view, the delegates and the widget ([[appendices.logging]]); rehuco hosts it as an app-wide log dock and one per open resource — see below for what was and was not carried |
| `widgets/flow_layout`, `line_edit` | `borco_pyside/widgets/` (`flow_layout`, `line_edit_helpers`, `line_edit_clear_action`, …) — a wider set than either snapshot |
| `markdown/` editor + viewer (1st only) | Not carried as-is: `rich_text_view` covers viewing; the Markdown **editor** is planned on **pyside6-scintilla** |
| `image_browser/` (1st only) | Not carried: the image strip/lightbox is tutorial-plugin work (**LocalEdit5**), and the image grid is a planned QML surface |
| Atomic write — *no pyside-ibo equivalent* | `borco_core/atomic_write.py` — new (LocalEdit1's atomic save) |
| Theming, QtAds helpers, dockable dialogs — *no pyside-ibo equivalent* | `borco_pyside/theming`, `qtads`, `dialogs` — new in rehuco |

### The in-app log surface

[[[pyside-ibo#log-stack]]]

For a long time the single biggest thing pyside-ibo had that rehuco did not: `borco_pyside/logging/`
was **one function** — `setup_console_logging()`, colorized console output via colorama (~23 lines) —
while pyside-ibo shipped an entire in-app log viewer:

- **`LogWidgetBridge(logging.Handler)`** — the interesting part. It plugs into Python's stdlib
  logging as a handler, **caches every record it receives**, and forwards them to any widget
  implementing the `SupportsLogging` protocol (`handle_log_record(record, message)` + a `cleared`
  signal). Because it caches, attaching the widget *later* replays everything already logged — so
  records emitted before the GUI existed (startup, early failures) are not lost.
- **`LogModel`** (`QAbstractTableModel`) + **`LogFilterModel`** (`QSortFilterProxyModel`) — records
  as filterable table data.
- **`LogView`** (`QTableView`) + **`LogLevelDelegate`** / **`LogMessageDelegate`** — per-level
  painting.
- **`LogWidget`** / **`LogWindow`** (the 1st snapshot used a `log_widget_mixin` instead) — the
  dockable/standalone surface the user actually reads.

**Status in rehuco: built** — the non-GUI half in #199, the surfaces in #200. `LogBridge`, `LogModel`,
`LogFilterModel`, the `LogRecordSink` protocol, `LogView`, the two delegates and `LogWidget` all live in
`borco_pyside/logging/`, specified in [[appendices.logging]]; rehuco hosts that widget twice, as the
window's own log dock and as one per open resource ([[appendices.logging#surfaces]]).

The cache-then-replay design was the piece worth reusing and was. Three things were deliberately not
carried from the **bridge**: the **names** (`LogWidgetBridge`/`SupportsLogging`) went, because the bridge
never imports a widget; the sink takes a **batch** rather than a record, because the per-record shape
cannot survive a job logging once per file; and there is now **more than one sink**, each scoped and
cleared independently ([[appendices.logging#routing]]) — where the prior art had a single `widget` and
wired its `cleared` signal back to `clear_cache()`, so emptying the view also erased the replay buffer.

From the **view and delegates**, the shape was carried and three things corrected:

- **Bands, not a ladder of named levels.** The prior art's level delegate chose its color with
  `if 0 <= level <= DEBUG … elif level <= INFO …`, so a record logged at 15 or past `CRITICAL` fell
  through to whatever came last. Classification is now `LogLevelBand.of` ([[appendices.logging#bands]]),
  which is total by construction.
- **Theme-aware tints, not a light-only table.** Its four hardcoded colors (`#DDDDDD`, `#FFFFFF`,
  `#FFFFCC`, `#FFCCCC`) are opaque fills that only read on a light theme, and this app has two. The
  colors are now supplied by the application and painted as a low-alpha wash over whatever the palette
  already drew, so one set works in both.
- **Follow-tail off the scroll position, not the wheel.** Its `LogView` existed to emit `wheel_rotated`,
  and auto-scroll was toggled from the angle delta — which misses a scrollbar drag, `Page Up`, `Home`
  and a keyboard selection, each of which leaves a reader being yanked back to the bottom. The
  scrollbar's position is where all of them end up, so that is what is read.

Also not carried: its `LogItem` (a mutable dataclass computing its own color) — `LogEntry` is frozen,
carries the scope and the run-long serial, and holds no opinion about how it is drawn.

**Originally none of this existed**, and it was scheduled first in LocalEdit7
([[implementation-plan]]) — ahead of the task queue/dock and the checksums that ride on it, on the
reasoning that the log dock is the simplest real dock and is what makes those two observable when
they misbehave. It landed on the QtAds shell already in place.

## Can rehuco work with it?

**Not applicable in the sidecar sense** — it defines no document format, so there is no data to
import. The relevant question is dependency, and that is settled: **rehuco does not depend on
pyside-ibo** and takes no submodule. The library's value is as prior art — most concretely the
`ApplicationSingleton` contract and the Windows registry recipes, both already re-expressed in
`borco-*` under current conventions.
