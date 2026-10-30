"""Finds the external tools on this machine, in the background, once ([[packaging-deployment#external-tools]], #521)."""

import logging
import threading
from collections.abc import Iterable
from functools import lru_cache
from typing import Final

from PySide6.QtCore import QObject, Signal, Slot
from rehuco_core import EXTERNAL_TOOLS, ToolCandidate, ToolDescriptor, ToolLocator, shared_tool_locator

from .tools_settings import ToolDetection, ToolsSettings, shared_tools_settings

logger = logging.getLogger(__name__)


class ToolDiscovery(QObject):
    """Searches for every external tool on a thread of its own, and records what it finds in `ToolsSettings`.

    **Each tool is searched for once.** A tool already searched for is only *verified* -- its stored installs are kept
    while their executables are still there, with nothing searched for and no version read -- so a start costs a few
    file checks. A tool never searched for is searched for: that is the first start, and also the resume of a run that
    was interrupted, since each tool's result is recorded as soon as it is in, and the settings are written when the
    window closes (:meth:`~rehuco_agent.settings.tools_settings.ToolsSettings.save`). A search is forced for a tool by
    :meth:`start`'s ``force``, which is what the Tools page's Detect does.

    **Only usable installs are recorded.** A search judges every copy it finds, and what it rejects -- a static build,
    one too old, one that does not run -- is logged once at WARNING with its folder and reason, and not kept: nobody
    acts on an unusable row in the Tools page, and seven greyed rows hid the one that mattered (#319, #592). A path the
    user typed is judged elsewhere and shown with its reason, since they asked about that one.

    **A daemon thread**, with an event to stop it ([[appendices.code-conventions#worker-threads]]): a search can block
    on a disk or a share the app does not control, and quitting must not wait for it. The thread touches no Qt object
    and writes nothing: it only emits a signal, which Qt queues to the GUI thread, where the result is recorded.

    :param settings: where the results are recorded and the stored ones read.
    :param locator: searches and verifies; the process-wide one when omitted.
    :param parent: optional Qt parent.
    """

    tool_done = Signal(str)
    """A tool's search or verification has been recorded, on the GUI thread; the argument is the tool's id."""

    reported = Signal(int, str, bool, object)
    """The thread's report, ``(generation, tool id, searched, installs)``: emitted on the thread, delivered to
    :meth:`__deliver` on this object's own. Internal; connect to :attr:`tool_done`."""

    def __init__(
        self,
        settings: ToolsSettings,
        locator: ToolLocator | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__settings: Final = settings
        self.__locator: Final = locator if locator is not None else shared_tool_locator()
        self.__generation = 0
        self.__stop = threading.Event()
        self.reported.connect(self.__deliver)

    def start(self, force: Iterable[str] = ()) -> None:
        """Go over every tool: search for those never searched for or in ``force``, verify the rest.

        A run already going is dropped: its remaining tools are not visited and its late answer is ignored.

        :param force: the ids of tools to search for again, whatever is stored.
        """
        self.__stop.set()
        self.__stop = threading.Event()
        self.__generation += 1
        forced = set(force)
        plan = [(tool, self.__settings.detection(tool.ID), tool.ID in forced) for tool in EXTERNAL_TOOLS.values()]
        threading.Thread(
            target=self.__run, args=(self.__generation, self.__stop, plan), name="tool-discovery", daemon=True
        ).start()

    def stop(self) -> None:
        """Stop the run going and ignore whatever it still reports; the thread is left to end by itself."""
        self.__stop.set()
        self.__generation += 1

    def __run(
        self, generation: int, stop: threading.Event, plan: list[tuple[ToolDescriptor, ToolDetection, bool]]
    ) -> None:
        """Visit each tool on the thread, reporting each as it is done.

        :param generation: this run's number, for :meth:`__deliver` to judge.
        :param stop: set when this run is outdated or the app is closing.
        :param plan: each tool, what is stored for it, and whether to search for it whatever is.
        """
        for tool, stored, forced in plan:
            if stop.is_set():
                return
            searched, installs = self.__visit(tool, stored, forced)
            try:
                self.reported.emit(generation, tool.ID, searched, installs)
            except RuntimeError:  # this object was deleted while the thread ran
                return

    def __visit(
        self, tool: ToolDescriptor, stored: ToolDetection, forced: bool
    ) -> tuple[bool, tuple[ToolCandidate, ...]]:
        """Search for one tool, or verify what is stored for it.

        :param tool: the tool.
        :param stored: what is stored for it.
        :param forced: whether to search whatever is stored.
        :returns: whether it has now been searched for, and its installs. A search that fails is logged and leaves the
            tool as it was, to be tried again at the next start.
        """
        try:
            if stored.searched and not forced:
                return True, tuple(self.__locator.verify(tool, stored.installs))
            return True, self.__usable_only(tool, self.__locator.detect(tool))
        except Exception:  # pylint: disable=broad-exception-caught
            # whatever the search raised, the other tools are still to be visited
            logger.warning("Searching for %s failed.", tool.LABEL, exc_info=True)
            return stored.searched, stored.installs

    @staticmethod
    def __usable_only(tool: ToolDescriptor, found: Iterable[ToolCandidate]) -> tuple[ToolCandidate, ...]:
        """Keep the installs a feature may use, logging each of the others.

        :param tool: the tool.
        :param found: every copy the search judged.
        :returns: the usable ones, in their order.
        """
        kept: list[ToolCandidate] = []
        for candidate in found:
            if candidate.is_usable:
                kept.append(candidate)
            else:
                logger.warning(
                    "%s at %s (%s) is not usable: %s", tool.LABEL, candidate.folder, candidate.source, candidate.reason
                )
        return tuple(kept)

    @Slot(int, str, bool, object)
    def __deliver(self, generation: int, tool_id: str, searched: bool, installs: object) -> None:
        """Record a tool's result unless a later run or :meth:`stop` outdated it.

        :param generation: the run's number.
        :param tool_id: the tool.
        :param searched: whether it has been searched for.
        :param installs: its installs, a tuple of candidates.
        """
        if generation != self.__generation:
            return
        self.__settings.set_detection(tool_id, ToolDetection(searched, tuple(installs)))  # type: ignore[arg-type]
        self.tool_done.emit(tool_id)


@lru_cache(maxsize=1)
def shared_tool_discovery() -> ToolDiscovery:
    """The process-wide discovery, over the shared settings and locator -- one, so a Detect on the Tools page and the
    start-up search are the same run.

    :returns: the shared instance.
    """
    return ToolDiscovery(shared_tools_settings())
