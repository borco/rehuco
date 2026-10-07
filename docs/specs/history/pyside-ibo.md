# pyside-ibo

<https://gitlab.com/iborco-software/python/pyside-ibo>

<https://gitlab.com/iborco-software/python/pyside-ibo-obsolete>

Not an application but the shared **PySide6 utility library** the last two predecessors consumed as a
git submodule — "common classes and widgets for PySide6 projects." It exists in two generations
that share a name: TutCatalog5 used the first, Resource Hub a ground-up second.

## The two snapshots

| | pyside-ibo-obsolete (1st) | pyside-ibo (2nd) |
| --- | --- | --- |
| Period | 2025/05/07 – 2025/05/31 | 2026/05/04 – 2026/06/04 |
| Commits | 108 | 96 |
| Consumed by | [TutCatalog5](tutcatalog5.md) | [Resource Hub](resource-hub.md) |
| Declares | `name = "pyside-ibo"`, `version = "0.1.0"` | `name = "pyside-ibo"`, `version = "0.1.0"` |

Both share one `.gitmodules` URL, so only the pinned submodule commit tells them apart (TutCatalog5 pins `7a82b82`, in `pyside-ibo-obsolete`; Resource Hub pins `86f0085`, in `pyside-ibo`).

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

## Ledger: what is in the code, and is it still worth digging out

rehuco depends on neither snapshot; what it needs lives in `borco-core` / `borco-pyside`. The last column is the
question that matters here: does the old code still hold something not yet in rehuco?

| pyside-ibo module | Counterpart in rehuco | Worth digging out? |
| --- | --- | --- |
| `application_singleton` (2nd) | Built — `borco_pyside/core/application_singleton.py` | No |
| `properties` (2nd) | Built — `SimpleProperty`, `TypedProperty` for `ObjectProperty` | No |
| `connection_list` (both) | Built — `borco_pyside/core/connection_list.py` | No |
| `logging/` (both) | Built — `borco_pyside/logging/`, see below | No |
| `sys/windows/registry` (both) | Built — `borco_core/platforms/windows/` | No |
| `sys/windows/utils` (1st): open in code editor, reveal in file explorer | Reveal built — `borco_pyside/file_browser.py`; open-in-editor not carried | TBD |
| `markdown/` viewer (1st) | Built — `rich_text_view` | No |
| `markdown/` editor (1st) | Built differently — on pyside6-scintilla | No |
| `image_browser/` (1st): list model, view, delegate, single view | Strip and lightbox built; a grid over a library is [#403](https://github.com/borco/rehuco/issues/403) | **Yes** — the one piece of the 1st snapshot that #403 could start from |
| `widgets/flow_layout`, `line_edit` (1st) | Built — `borco_pyside/widgets/` | No |
| `widgets/hidden_tool_button` (1st): a button shown only on hover or press | Not carried | TBD |
| `widgets/path_edit_widget` (1st) | Not carried; rehuco's path field is its own | TBD |
| `widgets/single_selection_widget` (1st) | Not carried | TBD |
| `core/settings`, `path_mixin`, `unique_keys_enum` (1st) | Not carried; rehuco has its own persistent-settings helpers | TBD |
| `core/exceptions.raise_with_stacklevel`, `core/datetime.utcnow` (2nd) | Not carried | TBD |

### The in-app log surface

[[[pyside-ibo#log-stack]]]

What pyside-ibo's logging had, and where rehuco's `borco_pyside/logging/` differs:

- **`LogWidgetBridge`**, a `logging.Handler` that caches every record and replays them to a widget attached later.
  Carried as `LogBridge`; the sink takes a batch, not a record, and there can be several sinks, each scoped and
  cleared independently ([[appendices.logging#routing]]). pyside-ibo had one widget, whose clear also emptied the cache.
- **`LogModel`, `LogFilterModel`, `LogView`, the level and message delegates, `LogWidget` / `LogWindow`.** Carried.
  Level colours are classified by `LogLevelBand.of` ([[appendices.logging#bands]]) rather than an `if` ladder that
  missed levels between the named ones, painted as a low-alpha wash so one set works in both themes, and follow-tail
  reads the scrollbar position rather than the wheel.
- **`LogItem`**, a mutable dataclass that picked its own colour. Not carried; `LogEntry` is frozen and carries the scope
  and a run-long serial.

## Importing its data

None — it defines no document format.
