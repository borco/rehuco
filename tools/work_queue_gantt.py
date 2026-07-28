"""Schedule a markdown work queue and draw it as a mermaid Gantt chart.

Reads the plan out of a markdown document (default ``continue_prompt_x.md``, gitignored), packs it into
working days, and writes a ``.mermaid`` file showing the plan plus an *Actual* track dated from each
issue's GitHub close time. The queue document is the only source of truth: this tool decides nothing
about the work, and every input below is read from it.

    REGENERATE                uv run python tools/work_queue_gantt.py
    RECONCILE WITH GITHUB     uv run python tools/work_queue_gantt.py --check
    PUSH TO THE PROJECT BOARD uv run python tools/work_queue_gantt.py --gh
    RECORD FINISHED WORK      tick a row's `Done` cell with a check, then --compact
    RE-PLAN                   --hours 7 / --start 2026-08-03 / --width 2600

    THREE OUTPUT FORMATS, written together by default (--mermaid / --plantuml / --markwhen pick one):
        .mermaid    renders in VSCode's markdown preview and on GitHub. Sections, a red bar for
                    anything another row needs, and a separate Actual track. No dependency arrows --
                    mermaid gantt has none.
        .plantuml   renders through the PlantUML server this repo already configures. Draws real
                    dependency arrows, per-task completion, and skips closed days itself. It has no
                    intra-day placement, so tasks are chained and durations scaled -- see
                    :func:`render_plantuml`. `--zoom` is what makes the bars wide enough to see.
        .mw         Markwhen, for its VSCode extension: the most legible source of the three, with
                    real times rather than scaled ones, and no dependency notion at all.

THE QUEUE DOCUMENT'S FORMAT
    Written out in full so the document can be rebuilt from scratch if it is ever lost -- it is
    gitignored, and this tool is not.

    A **schedulable table** is any markdown table immediately preceded by a marker comment::

        <!-- gantt: band=Distribution order=1 -->
        | Done | # | Issue | Model | Size | Needs | Work |
        | --- | --- | --- | --- | --- | --- | --- |
        | | 1 | #207 | opusplan | S | — | Decide the Linux format |
        | ✔ | 2 | #206 | opusplan | L | #207 | Briefcase desktop build |

    ``band`` names the Gantt row-group; ``order`` is when that group is worked, and every table sharing
    a band should share its order. **order=0 means listed but not scheduled** -- the row is reported as
    a deliberate exclusion rather than as an omission. A table with *no* marker is not scheduled either
    (its last cell is read as the reason), which is how a "next up" summary table or a filing-debt table
    avoids being counted twice.

    Cells are matched **by shape, not by position**, so tables may carry different columns:

    ==================  =========================================================================
    the first cell      the ``Done`` tick -- one of :data:`TICKS`, or empty
    ``#123``            the issue number; a row without one is not a work row
    ``XS S M L XL``     the size, which is what the bar's length comes from (:data:`SIZE_HOURS`)
    a name in MODELS    which model to use; defaults to ``sonnet`` when absent
    second-to-last      ``Needs``: hard prerequisites as ``#123, #456``, or ``—`` for none
    the last cell       the work itself, shortened into the bar's label
    ==================  =========================================================================

    A row whose issue another row *needs* is drawn red, and :func:`check` fails if it is scheduled after
    something that needs it. Anything outside a marked table is prose and is ignored.

THE .done FILE
    Line 1 is the plan's **frozen start date**. No date there (or no file) means the plan starts
    *tomorrow*, whenever it is run -- so emptying the file is a deliberate reset to an unstarted plan.

    Everything after line 1 is table blocks moved out of the queue by ``--compact``, verbatim, each
    under its own marker and header. This file is parsed **before** the queue, so the two together still
    reconstruct the whole original plan: compacting shortens the document without shortening the chart.

    Completion dates are not stored here -- they are read from each issue's GitHub close time when the
    chart is drawn. Closing is a proxy for finishing, which holds where an issue closes when its branch
    merges.

THE PROJECT BOARD, AS A FOURTH OUTPUT
    ``--gh`` writes each scheduled row's planned day onto the two date fields a GitHub roadmap view
    draws its bars between (:data:`DATE_FIELDS`), making the board a fourth rendering of this same
    schedule rather than a second, hand-kept version of it. Without it the board is a snapshot: the
    chart redraws on every run, the board does not, so ticking a row silently leaves stale bars behind.

    **Start and target are the same day.** The schedule packs several issues into one working day and a
    roadmap cannot draw anything finer than a day, so every bar is a one-day block and issues sharing a
    day form a column. Widening the bars would make the board disagree with the chart, which is the one
    thing this flag exists to prevent.

    A row the plan no longer schedules has its dates *cleared*, so a bar cannot outlive the row that put
    it there. Issues absent from the board are reported rather than added -- board membership is a
    decision this tool does not make -- and are the one thing that makes ``--gh`` exit non-zero.

WHY THE CLOCK TIMES ARE FAKE
    A worked day is drawn as the whole calendar day, so a 1h bar is 1/6 of a day rather than 1/24 of
    one -- otherwise every bar is an unreadable sliver. The dates are exact; the times are not.
"""

import argparse
import datetime
import json
import pathlib
import re
import shutil
import subprocess
from typing import Any, Final

HOURS_PER_DAY: Final = 6.0
"""Nominal agentic hours per working day."""

SIZE_HOURS: Final = {"XS": 0.5, "S": 1.0, "M": 2.0, "L": 4.0, "XL": 8.0}
"""Each size label charged at its **upper** bound: the scale is agent-time and already doubling, so a
bar is a ceiling rather than a mean."""

MODELS: Final = frozenset({"sonnet", "opus", "opusplan", "fable"})

TICKS: Final = frozenset({"x", "X", "yes", "done", "✓", "✔", "✅"})
"""What counts as a hand-written tick in a row's ``Done`` cell."""

BAND_RE: Final = re.compile(r"<!--\s*gantt:\s*band=(?P<band>\S+)\s+order=(?P<order>\d+)\s*-->")
"""The marker the queue document carries above each schedulable table."""

ISSUE_RE: Final = re.compile(r"#\d+")

PROJECT: Final = "borco/5"
"""The user project ``--gh`` writes to, as ``owner/number``."""

DATE_FIELDS: Final = ("Start date", "Target date")
"""The project's two date fields, in the order a roadmap view draws a bar between them."""

MUTATIONS_PER_REQUEST: Final = 25
"""How many aliased field writes go in one GraphQL document -- 100 field values in four requests."""

NODE_ID_RE: Final = re.compile(r"[A-Za-z0-9_-]+")
"""What a GitHub node id may contain, checked before one is inlined into a mutation."""

PROJECT_QUERY: Final = """
query($owner: String!, $number: Int!) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 50) { nodes { ... on ProjectV2FieldCommon { id name } } }
    }
  }
}
"""

ITEMS_QUERY: Final = """
query($owner: String!, $number: Int!, $cursor: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content { ... on Issue { number } }
          fieldValues(first: 30) {
            nodes {
              ... on ProjectV2ItemFieldDateValue {
                date
                field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""

WORKDAY_STARTS: Final = 9
"""The hour a working day is drawn as beginning. Presentation only -- the schedule counts hours, not
clock times, and only the dates it produces are meaningful."""


def clean_title(cell: str) -> str:
    """Reduce a work-column cell to a bar label: no markup, no trailing explanation, not too long.

    :param cell: the table cell as written in the document.
    :returns: a short plain-text label.
    """
    text = re.sub(r"[*`]", "", cell).strip()  # not `_`: emphasis in prose, but part of identifiers
    text = re.split(r"\s+[-—]\s+|;\s+", text)[0].strip()
    text = re.sub(r"\s+", " ", text.replace(":", " ").replace(",", " "))
    return text if len(text) <= 48 else text[:47].rstrip() + "..."


def baseline_of(path: pathlib.Path) -> datetime.date | None:
    """The plan's frozen start, from the first non-empty line of the ``.done`` file.

    :param path: the ``.done`` file; absent, empty, or headed by anything else means no baseline.
    :returns: the start date, or ``None`` -- in which case the plan starts tomorrow, whenever that is.
    """
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                return datetime.date.fromisoformat(line.strip())
            except ValueError:
                return None
    return None


def parse_row(cells: list[str], band: str, order: int, compacted: bool) -> dict[str, Any] | None:
    """Read one table row, matching cells by shape rather than by position.

    :param cells: the row's cells, already stripped.
    :param band: the band its table declared.
    :param order: the order its table declared.
    :param compacted: whether it came from the ``.done`` file rather than the queue.
    :returns: the parsed row, or ``None`` when the line is not a work row.
    """
    number = next((cell for cell in cells if ISSUE_RE.fullmatch(cell)), None)
    size = next((cell for cell in cells if cell in SIZE_HOURS), None)
    if number is None or size is None:
        return None
    return {
        "band": band,
        "order": order,
        "issue": int(number[1:]),
        "size": size,
        "model": next((cell for cell in cells if cell in MODELS), "sonnet"),
        "title": clean_title(cells[-1]),
        "needs": [int(ref) for ref in re.findall(r"#(\d+)", cells[-2])] if len(cells) > 1 else [],
        "ticked": cells[0] in TICKS,
        "compacted": compacted,
    }


def parse_queue(*paths: pathlib.Path) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Read every schedulable row out of the given documents.

    :param paths: the documents to read, in plan order -- the ``.done`` file first, so a compacted row
        keeps its original place in the schedule.
    :returns: the rows ordered by their table's declared ``order``, and the ``{issue: reason}`` map of
        issues that appear only in unmarked or ``order=0`` tables.
    :raises SystemExit: if nothing was found at all, which means the table format moved.
    """
    band, order = "", 0
    found: list[dict[str, Any]] = []
    excluded: dict[int, str] = {}
    for source in paths:
        if not source.exists():
            continue
        for line in source.read_text(encoding="utf-8").splitlines():
            marker = BAND_RE.search(line)
            if marker:
                band, order = marker["band"], int(marker["order"])
                continue
            if line.startswith("## "):
                band, order = "", 0  # left the scheduled sections; what follows is unscheduled
                continue
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            row = parse_row(cells, band, order, compacted=source != paths[-1])
            if row is None:
                continue
            if not band or order == 0:
                excluded.setdefault(row["issue"], cells[-1])
            elif not any(other["issue"] == row["issue"] for other in found):
                found.append(row)
    if not found:
        raise SystemExit("no rows found -- has the table format or the gantt markers changed?")
    for row in found:
        row["blocks"] = any(row["issue"] in other["needs"] for other in found)
    scheduled = {row["issue"] for row in found}
    return sorted(found, key=lambda row: row["order"]), {
        issue: reason for issue, reason in excluded.items() if issue not in scheduled
    }


def next_working(day: datetime.date) -> datetime.date:
    """The next day that is not a Sunday.

    :param day: the day to advance from.
    :returns: the following working day.
    """
    day += datetime.timedelta(days=1)
    while day.weekday() == 6:
        day += datetime.timedelta(days=1)
    return day


def schedule(rows: list[dict[str, Any]], start: datetime.date, hours_per_day: float) -> list[dict[str, Any]]:
    """Pack the rows into working days, never splitting one across a day boundary.

    :param rows: the parsed rows; each gains ``begins`` and ``hours``.
    :param start: the first working day.
    :param hours_per_day: agentic hours available per day.
    :returns: the same rows, scheduled.
    """
    day, used = start, 0.0
    scale = 24.0 / hours_per_day
    for row in rows:
        hours = SIZE_HOURS[row["size"]]
        if used + hours > hours_per_day + 1e-9:
            day, used = next_working(day), 0.0
        row["begins"] = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(hours=used * scale)
        row["hours"] = hours
        used += hours
    return rows


def plan_bar(row: dict[str, Any], hours_per_day: float) -> str:
    """One plan bar.

    :param row: a scheduled row.
    :param hours_per_day: agentic hours per day, for the day scale.
    :returns: the mermaid task line.
    """
    drawn = row["hours"] * 24.0 / hours_per_day
    duration = f"{int(drawn)}h" if drawn == int(drawn) else f"{int(drawn * 60)}m"
    tag = "crit, " if row["blocks"] else ""
    label = f"#{row['issue']} {row['title']} [{row['size']} {row['model']}]"
    return f"    {label} :{tag}i{row['issue']}, {row['begins']:%Y-%m-%d %H:%M}, {duration}"


def actual_bar(row: dict[str, Any], landed: datetime.date, hours_per_day: float) -> str:
    """One Actual-track bar, drawn on the day the issue closed.

    :param row: a scheduled row that is finished.
    :param landed: the day GitHub says its issue closed.
    :param hours_per_day: agentic hours per day, for the day scale.
    :returns: the mermaid task line, annotated with the drift from its planned day.
    """
    drawn = row["hours"] * 24.0 / hours_per_day
    duration = f"{int(drawn)}h" if drawn == int(drawn) else f"{int(drawn * 60)}m"
    slipped = (landed - row["begins"].date()).days
    drift = f" {slipped:+d}d" if slipped else ""
    return f"    #{row['issue']} {row['title']}{drift} :done, a{row['issue']}, {landed:%Y-%m-%d} 00:00, {duration}"


def render_mermaid(
    rows: list[dict[str, Any]], closed: dict[int, datetime.date], hours_per_day: float, width: int
) -> str:
    """Render the plan, and the Actual track beneath it, as a mermaid gantt document.

    :param rows: the output of :func:`schedule`.
    :param closed: ``{issue: close date}`` from GitHub, which dates the Actual track.
    :param hours_per_day: agentic hours per day, for the day scale.
    :param width: canvas width in pixels.
    :returns: the complete ``.mermaid`` document.
    """
    # the diagram keyword must be the first line after any frontmatter -- a %% header above it is a
    # parse error, so the generated-by note lives inside the body instead
    lines = [
        f"""---
config:
  gantt:
    useWidth: {width}
    barHeight: 18
    barGap: 3
    leftPadding: 220
    rightPadding: 40
    fontSize: 12
---
gantt
    title rehuco work queue
    dateFormat YYYY-MM-DD HH:mm
    axisFormat %a %d %b
    tickInterval 1day
    excludes sunday

    %% GENERATED by tools/work_queue_gantt.py -- do not hand-edit; edit the queue document instead.
    %% Its assumptions, and the format it reads, are documented in that script's docstring.
"""
    ]
    band = None
    for row in rows:
        if row["band"] != band:
            band = row["band"]
            lines.append(f"\n    section {band}")
        lines.append(plan_bar(row, hours_per_day))

    # every finished row, drawn on the day GitHub says its issue closed. A row that is finished but
    # whose issue is still open -- or unreachable -- simply does not appear here.
    executed = [row for row in rows if (row["ticked"] or row["compacted"]) and row["issue"] in closed]
    if executed:
        lines.append("\n    section Actual")
        lines.extend(
            actual_bar(row, closed[row["issue"]], hours_per_day)
            for row in sorted(executed, key=lambda item: closed[item["issue"]])
        )
    return "\n".join(lines) + "\n"


def render_plantuml(
    rows: list[dict[str, Any]], closed: dict[int, datetime.date], hours_per_day: float, zoom: int
) -> str:
    """Render the plan as a PlantUML gantt.

    **PlantUML gantt has no intra-day placement.** ``starts <date> at <time>`` parses but the time is
    ignored, so every task on a day would begin at 00:00 and sit on top of its neighbours. The only way
    to order tasks within a day is to chain them -- ``starts at [previous]'s end`` -- which is also what
    earns the dependency arrows mermaid cannot draw.

    Durations are **scaled** by ``24 / hours_per_day`` so a working day fills its calendar day rather
    than the first quarter of it -- otherwise the bars are slivers and three quarters of the chart is
    empty. Dates stay exact regardless, because the first task of each day is *also* pinned to its date:
    chaining orders the tasks within a day, and the pin puts each day where the schedule says.

    The cost is the start/end/duration table PlantUML always draws beside the chart -- there is no
    directive to hide it, every spelling but ``hide footbox`` is rejected -- whose Duration column is
    therefore in scaled hours. Divide by the scale to read real effort; the queue document has it exact.

    :param rows: the output of :func:`schedule`.
    :param closed: ``{issue: close date}`` from GitHub, for per-task completion.
    :param hours_per_day: agentic hours per day, which sets the duration scale.
    :param zoom: the daily print scale; without it every sub-day bar is a sliver.
    :returns: the complete ``.plantuml`` document.
    """
    scale = 24.0 / hours_per_day
    lines = [
        "@startgantt",
        "' GENERATED by tools/work_queue_gantt.py -- do not hand-edit; edit the queue document instead.",
        "'",
        "' Tasks are chained, which is the only way PlantUML orders work within a day, and what draws",
        "' the dependency arrows. The first task of each day is also pinned to its date, so the DATES",
        "' and the SEQUENCE are exact.",
        f"' Durations are scaled x{scale:g} so a {hours_per_day:g}h working day fills its calendar day;",
        f"' the table's Duration column is therefore in scaled hours -- divide by {scale:g} for real effort.",
        f"Project starts {rows[0]['begins']:%Y-%m-%d}",
        "sunday are closed",
        f"printscale daily zoom {zoom}",
    ]
    band, previous, day = None, "", None
    for row in rows:
        if row["band"] != band:
            band = row["band"]
            lines.append(f"-- {band} --")
        # no leading "#": PlantUML reads it as creole markup and renders the label as a numbered list
        # ("1. 164"). The label stays short -- the issue and the model it wants -- since the table
        # beside the chart already carries the dates and durations.
        name = f"[{row['issue']} ({row['model']})]"
        lines.append(f"{name} lasts {max(1, round(row['hours'] * scale))} hours")
        if previous:
            lines.append(f"{name} starts at {previous}'s end")
        # the chain alone would run on through a day this schedule deliberately left short, so the
        # first task of each day is *also* pinned to its date -- PlantUML honours both, keeping the
        # dependency arrow while putting the bar on the day the schedule actually assigned it
        if row["begins"].date() != day:
            day = row["begins"].date()
            lines.append(f"{name} starts {day:%Y-%m-%d}")
        if row["blocks"]:
            lines.append(f"{name} is colored in LightCoral")
        if row["issue"] in closed:
            lines.append(f"{name} is 100% completed")
        previous = name
    lines.append("@endgantt")
    return "\n".join(lines) + "\n"


def render_markwhen(rows: list[dict[str, Any]], closed: dict[int, datetime.date]) -> str:
    """Render the plan as a Markwhen timeline.

    Markwhen has no dependency notion, so ``Needs`` survives only as a note on the row. Unlike the other
    two it needs no scaling trick: it takes real times, so the working day is written as it is.

    :param rows: the output of :func:`schedule`.
    :param closed: ``{issue: close date}`` from GitHub, noted on each finished row.
    :returns: the complete ``.mw`` document.
    """
    lines = ["title: rehuco work queue", "", "#plan: #4a6fd4", "#done: #6c9e6c", ""]
    band, day, used = None, rows[0]["begins"].date(), 0.0
    for row in rows:
        if row["begins"].date() != day:
            day, used = row["begins"].date(), 0.0
        start = datetime.datetime.combine(day, datetime.time(WORKDAY_STARTS)) + datetime.timedelta(hours=used)
        finish = start + datetime.timedelta(hours=row["hours"])
        used += row["hours"]
        if row["band"] != band:
            if band is not None:
                lines.append("endGroup")
            band = row["band"]
            lines.append("")
            lines.append(f"group {band}")
        needs = f" (needs {', '.join(f'#{ref}' for ref in row['needs'])})" if row["needs"] else ""
        landed = f" [closed {closed[row['issue']]:%Y-%m-%d}]" if row["issue"] in closed else ""
        tag = "#done" if row["issue"] in closed else "#plan"
        lines.append(
            f"{start:%Y-%m-%d %H:%M}/{finish:%Y-%m-%d %H:%M}: "
            f"{row['issue']} {row['title']} [{row['size']} {row['model']}]{needs}{landed} {tag}"
        )
    if band is not None:
        lines.append("endGroup")
    return "\n".join(lines) + "\n"


def gh_json(*arguments: str) -> Any:
    """Run ``gh`` and parse its JSON output.

    The executable is resolved with :func:`shutil.which` and invoked without a shell, so a Windows
    ``gh.cmd`` still runs and nothing is passed through a command interpreter.

    :param arguments: the arguments after ``gh``.
    :returns: the decoded JSON -- a list for the ``issue list`` calls, an object for GraphQL.
    :raises RuntimeError: if ``gh`` is missing or the call fails -- offline is a fine reason to skip a
        reconciliation rather than an error worth raising to the user.
    """
    executable = shutil.which("gh")
    if executable is None:
        raise RuntimeError("gh is not on PATH")
    done = subprocess.run([executable, *arguments], capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"gh {' '.join(arguments)} failed")
    return json.loads(done.stdout)


def gh_graphql(query: str, **variables: Any) -> dict[str, Any]:
    """Run one GraphQL document through ``gh`` and return its ``data``.

    :param query: the document; passed as a raw string, so nothing in it is reinterpreted.
    :param variables: values for the variables it declares -- typed, so an ``Int!`` arrives as a number.
        A variable left out stays null, which is how the first page of a cursor walk is asked for.
    :returns: the ``data`` object.
    :raises RuntimeError: propagated from :func:`gh_json`, which is also how a GraphQL-level error
        arrives -- ``gh`` reports one as a non-zero exit.
    """
    arguments = ["api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        arguments += ["-F", f"{name}={value}"]
    return gh_json(*arguments)["data"]


def project_board(owner: str, number: int) -> dict[str, Any]:
    """Read the project's id, its field ids, and every item's issue number and current dates.

    :param owner: the user who owns the project.
    :param number: the project number.
    :returns: ``{"project": id, "fields": {name: id}, "items": {issue: id}, "dates": {issue: {name: day}}}``
        -- ``dates`` carries only the items that have at least one date set.
    :raises RuntimeError: propagated from :func:`gh_graphql`.
    """
    project = gh_graphql(PROJECT_QUERY, owner=owner, number=number)["user"]["projectV2"]
    board: dict[str, Any] = {
        "project": project["id"],
        "fields": {node["name"]: node["id"] for node in project["fields"]["nodes"] if node},
        "items": {},
        "dates": {},
    }
    cursor = None
    while True:
        page = gh_graphql(ITEMS_QUERY, owner=owner, number=number, **({"cursor": cursor} if cursor else {}))
        page = page["user"]["projectV2"]["items"]
        for node in page["nodes"]:
            issue = (node.get("content") or {}).get("number")
            if issue is None:  # a draft item or a pull request: nothing this plan schedules
                continue
            board["items"][issue] = node["id"]
            dates = {value["field"]["name"]: value["date"] for value in node["fieldValues"]["nodes"] if value}
            if dates:
                board["dates"][issue] = dates
        if not page["pageInfo"]["hasNextPage"]:
            return board
        cursor = page["pageInfo"]["endCursor"]


def date_mutation(alias: str, project: str, item: str, field: str, day: str) -> str:
    """One aliased date write, as GraphQL source.

    Values are inlined rather than bound as variables so that many writes fit in one document; each is
    an opaque id GitHub just handed back or a date this script formatted, and :data:`NODE_ID_RE` refuses
    anything that is not shaped like an id.

    :param alias: the alias naming this write within its document; must be unique there.
    :param project: the project's node id.
    :param item: the item's node id.
    :param field: the date field's node id.
    :param day: the day to write, as ``YYYY-MM-DD``.
    :returns: the mutation source line.
    :raises SystemExit: if an id is not shaped like one.
    """
    for value in (project, item, field):
        if not NODE_ID_RE.fullmatch(value):
            raise SystemExit(f"refusing to build a mutation around {value!r}")
    return (
        f'  {alias}: updateProjectV2ItemFieldValue(input: {{projectId: "{project}", itemId: "{item}", '
        f'fieldId: "{field}", value: {{date: "{day}"}}}}) {{ clientMutationId }}'
    )


def clear_mutation(alias: str, project: str, item: str, field: str) -> str:
    """One aliased field clear, as GraphQL source.

    :param alias: the alias naming this clear within its document; must be unique there.
    :param project: the project's node id.
    :param item: the item's node id.
    :param field: the date field's node id.
    :returns: the mutation source line.
    :raises SystemExit: if an id is not shaped like one.
    """
    for value in (project, item, field):
        if not NODE_ID_RE.fullmatch(value):
            raise SystemExit(f"refusing to build a mutation around {value!r}")
    return (
        f'  {alias}: clearProjectV2ItemFieldValue(input: {{projectId: "{project}", itemId: "{item}", '
        f'fieldId: "{field}"}}) {{ clientMutationId }}'
    )


def date_writes(board: dict[str, Any], planned: dict[int, str]) -> tuple[list[str], list[int]]:
    """The writes that make the board agree with the plan.

    An issue already carrying its planned day on both fields is skipped, so a re-run that changes
    nothing sends nothing.

    :param board: the output of :func:`project_board`.
    :param planned: ``{issue: day}`` for every scheduled row.
    :returns: the mutation source lines, and the scheduled issues that are not on the board at all.
    """
    calls: list[str] = []
    absent: list[int] = []
    for issue, day in planned.items():
        item = board["items"].get(issue)
        if item is None:
            absent.append(issue)
        elif not all(board["dates"].get(issue, {}).get(name) == day for name in DATE_FIELDS):
            calls += [
                date_mutation(f"w{len(calls) + index}", board["project"], item, board["fields"][name], day)
                for index, name in enumerate(DATE_FIELDS)
            ]
    return calls, sorted(absent)


def stale_clears(board: dict[str, Any], planned: dict[int, str]) -> tuple[list[str], list[int]]:
    """The clears that strip dates from items the plan no longer schedules.

    :param board: the output of :func:`project_board`.
    :param planned: ``{issue: day}`` for every scheduled row.
    :returns: the mutation source lines, and the issues they clear.
    """
    calls: list[str] = []
    cleared: list[int] = []
    for issue, current in sorted(board["dates"].items()):
        stale = [name for name in DATE_FIELDS if name in current] if issue not in planned else []
        if not stale:
            continue
        calls += [
            clear_mutation(f"c{len(calls) + index}", board["project"], board["items"][issue], board["fields"][name])
            for index, name in enumerate(stale)
        ]
        cleared.append(issue)
    return calls, cleared


def run_mutations(calls: list[str]) -> None:
    """Send the writes in batches, so a hundred field values cost a handful of requests.

    :param calls: aliased mutation source lines; aliases must be unique within each batch.
    :raises RuntimeError: propagated from :func:`gh_graphql` -- a failure part-way leaves the earlier
        batches applied, which is why the caller reports the board as half-written.
    """
    for offset in range(0, len(calls), MUTATIONS_PER_REQUEST):
        gh_graphql("mutation {\n" + "\n".join(calls[offset : offset + MUTATIONS_PER_REQUEST]) + "\n}")


def push(rows: list[dict[str, Any]], project: str) -> int:
    """Write every scheduled row's planned day onto the project's two date fields.

    :param rows: the output of :func:`schedule`.
    :param project: the project to write to, as ``owner/number``.
    :returns: a process exit code -- non-zero when a scheduled issue is not on the board, since the
        board then draws less than the plan holds.
    """
    owner, _, number = project.partition("/")
    if not number.isdigit():
        print(f"--project wants owner/number, not {project!r}")
        return 1
    try:
        board = project_board(owner, int(number))
    except (RuntimeError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"cannot read the project, nothing written: {error}")
        return 1
    if missing := [name for name in DATE_FIELDS if name not in board["fields"]]:
        print(f"the project has no {' and no '.join(repr(name) for name in missing)} field; add it and re-run")
        return 1

    planned = {row["issue"]: f"{row['begins']:%Y-%m-%d}" for row in rows}
    writes, absent = date_writes(board, planned)
    clears, cleared = stale_clears(board, planned)
    try:
        run_mutations(writes + clears)
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"the push failed part-way, so the board is half-written: {error}")
        return 1
    dated = len(writes) // len(DATE_FIELDS)
    print(
        f"{project}: {dated} issue(s) dated, {len(cleared)} cleared, "
        f"{len(planned) - len(absent) - dated} already correct"
    )
    if cleared:
        print(f"  no longer scheduled, dates removed: {' '.join(f'#{issue}' for issue in cleared)}")
    if absent:
        print(f"  scheduled but not on the board, so undrawn: {' '.join(f'#{issue}' for issue in absent)}")
    return 1 if absent else 0


def closed_dates() -> dict[int, datetime.date]:
    """When each closed issue was closed, as a plain local date.

    :returns: ``{number: date}`` for every recently closed issue.
    :raises RuntimeError: propagated from :func:`gh_json`.
    """
    closed = gh_json("issue", "list", "--state", "closed", "--limit", "300", "--json", "number,closedAt")
    return {
        issue["number"]: datetime.datetime.fromisoformat(issue["closedAt"]).astimezone().date()
        for issue in closed
        if issue.get("closedAt")
    }


def open_issues() -> dict[int, dict[str, Any]]:
    """Every open issue, by number, as GitHub currently has it.

    :returns: ``{number: {"size", "milestone", "title"}}``.
    :raises RuntimeError: propagated from :func:`gh_json`.
    """
    issues = {}
    for issue in gh_json(
        "issue", "list", "--state", "open", "--limit", "200", "--json", "number,title,labels,milestone"
    ):
        labels = {label["name"] for label in issue["labels"]}
        issues[issue["number"]] = {
            "size": next(iter(labels & set(SIZE_HOURS)), None),
            "milestone": (issue["milestone"] or {}).get("title"),
            "title": issue["title"],
        }
    return issues


def compact(queue: pathlib.Path, done: pathlib.Path) -> int:
    """Move every ticked row out of the queue document and into the ``.done`` file, verbatim.

    A moved row keeps its marker and header, so the ``.done`` file stays readable as tables and the two
    files still parse as one plan. A table that empties completely keeps its marker and header in the
    queue: an empty table is a visible reminder that a group is finished, and removing it is a
    judgement call about the prose around it.

    :param queue: the queue document, rewritten in place.
    :param done: the ``.done`` file, appended to.
    :returns: a process exit code.
    """
    marker, header, separator = "", "", ""
    kept: list[str] = []
    moved: dict[tuple[str, str, str], list[str]] = {}
    for line in queue.read_text(encoding="utf-8").splitlines():
        if BAND_RE.search(line):
            marker, header, separator = line, "", ""
        elif marker and line.startswith("|"):
            if not header:
                header = line
            elif not separator:
                separator = line
            elif line.strip().strip("|").split("|")[0].strip() in TICKS:
                moved.setdefault((marker, header, separator), []).append(line)
                continue
        elif not line.startswith("|"):
            marker = ""
        kept.append(line)

    if not moved:
        print("nothing ticked; the queue document is unchanged.")
        return 0

    blocks = done.read_text(encoding="utf-8").rstrip("\n") if done.exists() else ""
    for (block_marker, block_header, block_separator), rows in moved.items():
        if block_marker in blocks and block_header in blocks:
            blocks = blocks.replace(block_separator, block_separator + "\n" + "\n".join(rows), 1)
        else:
            block = "\n".join([block_marker, block_header, block_separator, *rows])
            blocks = f"{blocks}\n\n{block}" if blocks else block
    done.write_text(blocks + "\n", encoding="utf-8")
    queue.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"moved {sum(len(rows) for rows in moved.values())} row(s) from {queue} to {done}; regenerate to redraw.")
    return 0


def check(rows: list[dict[str, Any]], unscheduled: dict[int, str]) -> int:
    """Reconcile the queue against GitHub, and its ``Needs`` column against its own order.

    :param rows: the parsed rows, in scheduled order.
    :param unscheduled: the issues the document deliberately leaves out.
    :returns: a process exit code -- non-zero when anything disagrees.
    """
    problems = []
    position = {row["issue"]: index for index, row in enumerate(rows)}
    for index, row in enumerate(rows):
        for needed in row["needs"]:
            if needed not in position:
                problems.append(f"#{row['issue']} needs #{needed}, which is not scheduled at all")
            elif position[needed] > index:
                problems.append(f"#{row['issue']} is scheduled before #{needed}, which it needs")
    try:
        issues = open_issues()
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"cannot reach GitHub, checking the document against itself only: {error}")
        issues = {}
    for row in rows:
        issue = issues.get(row["issue"])
        if issues and issue is None:
            problems.append(f"#{row['issue']} {row['title']!r} is scheduled but no longer open")
        elif issue and issue["size"] != row["size"]:
            problems.append(f"#{row['issue']} is {issue['size'] or 'unsized'} on GitHub, {row['size']} in the queue")
    for number, issue in sorted(issues.items()):
        if number not in position and issue["milestone"] and number not in unscheduled:
            problems.append(f"#{number} ({issue['milestone']}) is open but not in the queue: {issue['title']}")
    for problem in problems:
        print(problem)
    print(f"{len(problems)} disagreement(s) found.")
    return 1 if problems else 0


def write_formats(rows: list[dict[str, Any]], closed: dict[int, datetime.date], args: argparse.Namespace) -> list[str]:
    """Write each requested output format beside the others.

    :param rows: the scheduled rows.
    :param closed: ``{issue: close date}`` from GitHub.
    :param args: the parsed command line, for the stem and the per-format options.
    :returns: the names of the files written.
    """
    written = []
    for name in args.formats or ["mermaid", "plantuml", "markwhen"]:
        if name == "mermaid":
            path, text = args.stem.with_suffix(".mermaid"), render_mermaid(rows, closed, args.hours, args.width)
        elif name == "plantuml":
            text = render_plantuml(rows, closed, args.hours, args.zoom)
            path = args.stem.with_suffix(".plantuml")
        else:
            path, text = args.stem.with_suffix(".mw"), render_markwhen(rows, closed)
        path.write_text(text, encoding="utf-8")
        written.append(path.name)
    return written


def parse_arguments() -> argparse.Namespace:
    """Build the command line.

    :returns: the parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queue", type=pathlib.Path, default=pathlib.Path("continue_prompt_x.md"))
    parser.add_argument("--done", type=pathlib.Path, default=pathlib.Path("continue_prompt_x_gantt.done"))
    parser.add_argument(
        "--stem",
        type=pathlib.Path,
        default=pathlib.Path("continue_prompt_x_gantt"),
        help="output path without a suffix; each format appends its own",
    )
    parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=["mermaid", "plantuml", "markwhen"],
        help="write only this format; repeatable, and all three are written when omitted",
    )
    for name in ("mermaid", "plantuml", "markwhen"):
        parser.add_argument(
            f"--{name}", dest="formats", action="append_const", const=name, help=f"shorthand for --format {name}"
        )
    parser.add_argument("--zoom", type=int, default=12, help="PlantUML daily print scale")
    parser.add_argument("--check", action="store_true", help="reconcile the queue against GitHub and exit")
    parser.add_argument("--gh", action="store_true", help="also push the schedule onto the project board's date fields")
    parser.add_argument("--project", default=PROJECT, help="the project --gh writes to, as owner/number")
    parser.add_argument("--compact", action="store_true", help="move ticked rows into the .done file")
    parser.add_argument("--start", type=datetime.date.fromisoformat, help="first working day (default: tomorrow)")
    parser.add_argument("--hours", type=float, default=HOURS_PER_DAY, help="agentic hours per day")
    parser.add_argument("--width", type=int, default=2600, help="canvas width in pixels")
    return parser.parse_args()


def main() -> int:
    """Compact, check, or regenerate -- and optionally push -- per the command line.

    :returns: a process exit code.
    """
    args = parse_arguments()
    if args.compact:
        return compact(args.queue, args.done)

    rows, unscheduled = parse_queue(args.done, args.queue)
    if args.check:
        return check(rows, unscheduled)
    try:
        closed = closed_dates()
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"cannot reach GitHub, drawing no Actual track: {error}")
        closed = {}

    baseline = baseline_of(args.done)
    start = args.start or baseline or datetime.date.today() + datetime.timedelta(days=1)
    while start.weekday() == 6:  # never start on the rest day
        start += datetime.timedelta(days=1)
    scheduled = schedule(rows, start, args.hours)
    written = write_formats(scheduled, closed, args)

    hours = sum(row["hours"] for row in scheduled)
    heavy = sum(row["hours"] for row in scheduled if row["size"] in ("L", "XL"))
    finished = sum(1 for row in scheduled if row["ticked"] or row["compacted"])
    origin = "the .done file" if baseline else "tomorrow (no date on the .done file's first line)"
    print(
        f"{len(scheduled)} issues -> {', '.join(written)}; {hours:g} agent-hours at {args.hours:g} h/day "
        f"= {hours / args.hours:.1f} working days, {start} -> {scheduled[-1]['begins']:%Y-%m-%d}"
    )
    print(
        f"  starting from {origin}; {finished} done, {len(unscheduled)} deliberately unscheduled, "
        f"L/XL rows carry {heavy / hours:.0%} of the hours"
    )
    # pushed from the same computation that drew the files, so the board cannot disagree with them
    return push(scheduled, args.project) if args.gh else 0


if __name__ == "__main__":
    raise SystemExit(main())
