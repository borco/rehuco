"""The scraper wizard registry: the user's own scripts first, then the built-ins
([[acquisition-tooling#library-wizard-protocol]], #683), and the saved queue's way back to a library scan.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Final, cast

from rehuco_core import DEFAULT_TASK_JOB_REGISTRY

from .library_scan_job import LIBRARY_SCAN_KIND, LibraryScanJob
from .library_site import LibrarySite
from .registry import BUILTIN_SOURCE_LABEL, ScraperRegistry, ScraperRow, shared_scraper_registry
from .role_report import RoleReport, RoleState
from .scraper_wizard import ScraperWizard
from .sites.fab_library import FabLibrary

LOG: Final = logging.getLogger(__name__)

BUILTIN_WIZARDS: Final[tuple[type[ScraperWizard], ...]] = (FabLibrary,)
"""The wizards this build ships: Fab's library scan (#684)."""

WIZARD_MARKER: Final = "create_job"
"""The `~.scraper_wizard.ScraperWizard` method that declares a class a wizard: one without it never meant to be one,
and one with it that lacks the rest is reported as broken."""


class ScraperWizardRegistry:
    """Finds the scraper wizards, a scripts-folder file's ahead of this build's own, by their key.

    **It scans nothing itself.** The classes of the user's scripts are the scraper registry's, which executes each file
    once for both; this registry looks through them again whenever that one has reloaded, so the Scrapers page's
    Reload and Save reach the wizards with no call of their own.

    **The user's wins on a shared key**: the first working wizard met under a key is the one offered, the folder's
    files in name order before the built-ins, and a later one is reported as replaced. A class that declares itself a
    wizard and cannot be one -- it needs arguments, lacks a member, names a key or a label that is not text -- is
    reported with the reason, never offered, and stops nothing else.

    :param scripts: the scraper registry whose scripts are looked through; ``None`` for the shared one.
    :param builtins: the built-in wizard classes.
    """

    @dataclass(frozen=True)
    class State:
        """What one look through the scripts found, swapped in as one unit.

        :param seen: the scraper registry's modules it was built from, by which a reload there is noticed.
        :param wizards: the wizards offered, by key.
        :param reports: how each class that declares itself a wizard fares, beside where it comes from.
        """

        seen: object = None
        wizards: dict[str, ScraperWizard] = field(default_factory=dict)
        reports: tuple[tuple[str, RoleReport], ...] = ()

    def __init__(
        self, scripts: ScraperRegistry | None = None, builtins: Iterable[type[ScraperWizard]] = BUILTIN_WIZARDS
    ) -> None:
        self.__scripts: Final = scripts if scripts is not None else shared_scraper_registry()
        self.__builtins: Final = tuple(builtins)
        self.__state = ScraperWizardRegistry.State()

    @property
    def wizards(self) -> tuple[ScraperWizard, ...]:
        """The wizards the dialog offers, the user's first.

        :returns: one wizard per key.
        """
        return tuple(self.__current().wizards.values())

    def find(self, key: str) -> ScraperWizard | None:
        """The wizard saved under ``key``.

        :param key: a wizard's :attr:`~.scraper_wizard.ScraperWizard.key`.
        :returns: the wizard, or ``None`` when none is installed.
        """
        return self.__current().wizards.get(key)

    def site(self, key: str) -> LibrarySite | None:
        """The library the wizard saved under ``key`` is read through: the wizard itself, when it is a site.

        This is the lookup a `~.library_scan_job.LibraryScanJob` is built with, asked again on every run.

        :param key: a wizard's key.
        :returns: the wizard as a site, or ``None`` when none is installed under ``key`` or it names no library.
        """
        wizard = self.__current().wizards.get(key)
        return wizard if isinstance(wizard, LibrarySite) else None

    def merged_rows(self, rows: Iterable[ScraperRow]) -> tuple[ScraperRow, ...]:
        """The Scrapers table's rows with the wizards in: a class that is a scraper too keeps its one row, a class
        that is only a wizard gets a row after its file's others, and a file is warned of declaring nothing only when
        it declares no wizard either.

        :param rows: the scraper registry's rows (`~.registry.ScraperRegistry.rows`).
        :returns: the table's rows, in the same order.
        """
        waiting: dict[str, list[RoleReport]] = {}
        for source, report in self.__current().reports:
            waiting.setdefault(source, []).append(report)
        merged: list[ScraperRow] = []
        previous: str | None = None
        for row in rows:
            if previous is not None and row.source != previous:
                merged.extend(self.__row(report, previous) for report in waiting.pop(previous, ()))
            previous = row.source
            reports = waiting.get(row.source, [])
            match = next((report for report in reports if report.class_key == row.class_key), None)
            if match is not None:
                reports.remove(match)
                merged.append(self.__with_wizard(row, match))
            elif row.warning and reports:
                # the file declares no scraper and does declare a wizard, whose rows stand in for the warning's
                continue
            else:
                merged.append(row)
        if previous is not None:
            merged.extend(self.__row(report, previous) for report in waiting.pop(previous, ()))
        for source, reports in waiting.items():
            merged.extend(self.__row(report, source) for report in reports)
        return tuple(merged)

    def __current(self) -> ScraperWizardRegistry.State:
        """What the scripts hold now, looked through again when the scraper registry has reloaded since.

        :returns: the state.
        """
        modules = self.__scripts.modules
        state = self.__state
        if state.seen is modules:
            return state
        candidates = [(module.path.name, candidate) for module in modules for candidate in module.classes]
        candidates.extend((BUILTIN_SOURCE_LABEL, builtin) for builtin in self.__builtins)
        wizards: dict[str, ScraperWizard] = {}
        sources: dict[str, str] = {}
        reports: list[tuple[str, RoleReport]] = []
        for source, candidate in candidates:
            report = self.__report(candidate)
            if report is None:
                continue
            key = getattr(report.instance, "key", None)
            if isinstance(key, str) and key in wizards:
                report = report.overridden(sources[key])
            elif isinstance(key, str) and report.state is RoleState.OK:
                wizards[key] = cast(ScraperWizard, report.instance)
                sources[key] = source
            if report.state is not RoleState.OK:
                LOG.info("The scraper wizard %s of %s is not offered: %s", candidate.__name__, source, report.problem)
            reports.append((source, report))
        state = ScraperWizardRegistry.State(modules, wizards, tuple(reports))
        self.__state = state
        return state

    @staticmethod
    def __report(candidate: type) -> RoleReport | None:
        """How ``candidate`` fares as a wizard, its key and its label having to be text.

        :param candidate: the class.
        :returns: the report; ``None`` for a class that does not declare itself a wizard.
        """
        report = RoleReport.of(candidate, ScraperWizard, WIZARD_MARKER)
        if report is None or report.state is not RoleState.OK:
            return report
        for name in ("key", "label"):
            value = getattr(report.instance, name)
            if not isinstance(value, str) or not value:
                return report.failed(f"{candidate.__name__}'s {name} is not a text")
        return report

    @staticmethod
    def __row(report: RoleReport, source: str) -> ScraperRow:
        """The row of a class that is only a wizard.

        :param report: how the class fares.
        :param source: the file's name, or the built-ins' label.
        :returns: the row, named by the wizard's label, or by the class when that cannot be read.
        """
        label = getattr(report.instance, "label", None)
        row = ScraperRow(
            key=None,
            label="",
            publisher="",
            site_name=label if isinstance(label, str) and label else report.owner.__name__,
            site_url="",
            source=source,
            needs_browser=False,
            error=None,
            class_key=report.class_key,
        )
        return ScraperWizardRegistry.__with_wizard(row, report)

    @staticmethod
    def __with_wizard(row: ScraperRow, report: RoleReport) -> ScraperRow:
        """A row with how its class fares as a wizard: a fault joins the row's error, a replacement is its note.

        :param row: the class's row.
        :param report: how the class fares as a wizard.
        :returns: the row.
        """
        if report.state is RoleState.OK:
            return replace(row, wizard=report.state)
        if report.state is RoleState.OVERRIDDEN_OK:
            return replace(row, wizard=report.state, note=report.problem)
        error = f"{row.error}; {report.problem}" if row.error else report.problem
        return replace(row, wizard=report.state, error=error)


@lru_cache(maxsize=1)
def shared_scraper_wizard_registry() -> ScraperWizardRegistry:
    """The one `ScraperWizardRegistry` the dialog, the Scrapers page and every saved scan share, over the shared
    scraper registry.

    :returns: the shared instance.
    """
    return ScraperWizardRegistry()


def register_library_scan_kind() -> None:
    """Say which job a saved ``library-scan`` is, so the queue restores one, finding its site in the shared registry.

    Called once the app starts, before the saved queue is read; asked again, it does nothing.
    """
    if LIBRARY_SCAN_KIND not in DEFAULT_TASK_JOB_REGISTRY.kinds:
        DEFAULT_TASK_JOB_REGISTRY.register(
            LIBRARY_SCAN_KIND, lambda: LibraryScanJob(shared_scraper_wizard_registry().site)
        )
