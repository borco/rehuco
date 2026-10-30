"""Where each optional external tool is, and which installs of it were found ([[packaging-deployment#external-tools]],
#521).

Two things are kept per tool, and **both stay whichever is in use**, so a custom path can be given up for an install
found before:

- the **path** the user chose -- empty for the newest usable install found. A path is the user's word for
  the machine this agent runs on, and is never sent anywhere ([[discovery-trust-access#remote-admin]]);
- the **detection** -- whether the tool was searched for, and every install that search found. It is written by
  `ToolDiscovery`, never by a feature, and no feature searches: they read it.

A reactive `QObject`, like `MarkdownRenderingSettings`: the Tools and Videos pages follow a tool changing, whoever
changed it. Changing a value only updates memory. The file is written by :meth:`save`, which the Tools page's Apply and
the window's close both call, so a discovery's progress is never a write of its own.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, cast

from PySide6.QtCore import QObject, QSettings, Signal
from rehuco_core import EXTERNAL_TOOLS, ToolCandidate, ToolDescriptor, shared_tool_locator

from .persistent_settings import persistent_settings

GROUP: Final = "tools"
PATH_KEY_TEMPLATE: Final = "{tool_id}_path"
DETECTED_KEY_TEMPLATE: Final = "{tool_id}_detected"
SEARCHED_KEY: Final = "searched"
INSTALLS_KEY: Final = "installs"


@dataclass(frozen=True)
class ToolDetection:
    """What searching for a tool found."""

    searched: bool = False
    """Whether the tool has been searched for. A tool that was and found nothing is not searched for again at the next
    start, only when the user presses Detect."""

    installs: tuple[ToolCandidate, ...] = ()
    """Every install found, newest usable first."""

    def to_text(self) -> str:
        """Spell this detection for the settings file.

        :returns: JSON text.
        """
        return json.dumps(
            {SEARCHED_KEY: self.searched, INSTALLS_KEY: [install.to_stored() for install in self.installs]}
        )

    @classmethod
    def from_text(cls, text: object) -> ToolDetection:
        """Read a detection the settings file holds, which another build or a hand edit may have written.

        :param text: the stored value, of any shape.
        :returns: what it holds; a tool never searched for when it is not readable.
        """
        try:
            raw = json.loads(text) if isinstance(text, str) else None
        except ValueError:
            raw = None
        if not isinstance(raw, dict):
            return cls()
        entries = raw.get(INSTALLS_KEY)
        stored = entries if isinstance(entries, list) else []
        installs = tuple(
            install for install in (ToolCandidate.from_stored(entry) for entry in stored) if install is not None
        )
        return cls(raw.get(SEARCHED_KEY) is True, installs)


class ToolsSettings(QObject):
    """The path and the detection of each external tool.

    :param parent: optional Qt parent.
    """

    tool_changed = Signal(str)
    """A tool's path or detection changed; the argument is the tool's id."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__paths: dict[str, str] = {}
        self.__detections: dict[str, ToolDetection] = {}

    def path(self, tool_id: str) -> str:
        """The path a tool is set to.

        :param tool_id: the tool's :attr:`~rehuco_core.ToolDescriptor.ID`.
        :returns: the path, or empty for the best install found.
        """
        return self.__paths.get(tool_id, "")

    def set_path(self, tool_id: str, path: str) -> None:
        """Set the path a tool is kept at, announcing a change.

        :param tool_id: the tool's id.
        :param path: the path, or empty for the best install found.
        """
        if self.path(tool_id) != path:
            self.__paths = {**self.__paths, tool_id: path}
            self.tool_changed.emit(tool_id)

    def detection(self, tool_id: str) -> ToolDetection:
        """What searching for a tool found.

        :param tool_id: the tool's id.
        :returns: the detection; a tool never searched for when there is none.
        """
        return self.__detections.get(tool_id, ToolDetection())

    def set_detection(self, tool_id: str, detection: ToolDetection) -> None:
        """Record what searching for a tool found, announcing a change. Memory only: :meth:`save` writes it.

        :param tool_id: the tool's id.
        :param detection: what was found.
        """
        if self.detection(tool_id) != detection:
            self.__detections = {**self.__detections, tool_id: detection}
            self.tool_changed.emit(tool_id)

    def unusable_reason(self, tool: ToolDescriptor) -> str | None:
        """Why a tool cannot be used as set up, searching for nothing.

        A chosen path is judged by the locator, which runs the tool for its version only the first time it sees that
        copy; an empty path reads what the detection holds.

        :param tool: the tool.
        :returns: ``None`` when a usable copy is set up, otherwise a sentence saying what is missing or wrong.
        """
        return self.__reason_of(tool, self.path(tool.ID))

    def missing_reason(self, tool: ToolDescriptor) -> str | None:
        """Why a tool cannot be used as set up, running nothing -- what a double-click on the GUI thread may ask.

        A chosen path is only checked to still hold the executables: its version gate is the Tools page's, which reads
        the version on a pool thread. An install the detection recorded carries the judgment it was found with, so for
        an empty path the answer is :meth:`unusable_reason`'s.

        :param tool: the tool.
        :returns: ``None`` when a copy is there to use, otherwise a sentence saying what is missing.
        """
        path = self.path(tool.ID)
        if path:
            return None if tool.resolve_folder(Path(path)) is not None else f"No {tool.LABEL} at {path}."
        return self.__reason_of(tool, "")

    def tool_folder(self, tool: ToolDescriptor) -> Path | None:
        """The folder holding the copy of a tool a feature runs, running nothing -- what a GUI-thread launch asks.

        :param tool: the tool.
        :returns: the folder of the chosen path, or of the best install found when the path is empty; ``None`` when
            there is none to use (:meth:`missing_reason` says why).
        """
        path = self.path(tool.ID)
        if path:
            return tool.resolve_folder(Path(path))
        candidate = shared_tool_locator().resolve(tool, "", self.detection(tool.ID).installs)
        return candidate.folder if candidate is not None and candidate.is_usable else None

    def __reason_of(self, tool: ToolDescriptor, path: str) -> str | None:
        """Ask the locator about the copy a path names.

        :param tool: the tool.
        :param path: the path the user chose, or empty for the best install found.
        :returns: ``None`` when it is usable, otherwise the reason.
        """
        candidate = shared_tool_locator().resolve(tool, path, self.detection(tool.ID).installs)
        if candidate is None:
            return f"No {tool.LABEL} was found, and none is set up."
        return None if candidate.is_usable else candidate.reason

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.__paths = {
            tool_id: cast(str, settings.value(PATH_KEY_TEMPLATE.format(tool_id=tool_id), "", type=str))
            for tool_id in EXTERNAL_TOOLS
        }
        self.__detections = {
            tool_id: ToolDetection.from_text(settings.value(DETECTED_KEY_TEMPLATE.format(tool_id=tool_id)))
            for tool_id in EXTERNAL_TOOLS
        }
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        for tool_id in EXTERNAL_TOOLS:
            settings.setValue(PATH_KEY_TEMPLATE.format(tool_id=tool_id), self.path(tool_id))
            settings.setValue(DETECTED_KEY_TEMPLATE.format(tool_id=tool_id), self.detection(tool_id).to_text())
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_tools_settings() -> ToolsSettings:
    """The single, process-wide `ToolsSettings`, loaded from persistent storage on first call -- the shape, and the
    reason, of :func:`~rehuco_agent.settings.videos_settings.shared_videos_settings`.

    :returns: the shared instance.
    """
    settings = ToolsSettings()
    settings.load(persistent_settings())
    return settings
