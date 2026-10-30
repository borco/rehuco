"""python-vlc bound to the user's libvlc, behind a proxy that works when there is none ([[appendices.vlc#python-vlc]],
#319).

``import vlc`` is where python-vlc searches for and loads libvlc, and it is unsafe to do blind: with no VLC found it
raises for a DLL in the working directory, a bad ``PYTHON_VLC_LIB_PATH`` makes it call ``sys.exit(1)``, and found the
usual way it changes the whole process's working directory while loading. So nothing here imports ``vlc`` at module
level. :class:`VlcLibrary` imports it once, by the full path of a library the Tools page resolved, inside a guard that
turns anything the import does into a reason; a child process (:func:`probe_libvlc`) has done the same with the same
library first, so a library that kills its process kills the probe, not the app.
"""

import importlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from .tool_descriptor import ToolStatus, Version

LOG: Final = logging.getLogger(__name__)

LIBRARY_PATH_VARIABLE: Final = "PYTHON_VLC_LIB_PATH"
"""The variable python-vlc reads the library's full path from, which skips its search and its ``chdir``."""

VERSION_PATTERN: Final = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
"""What ``libvlc_get_version`` starts with: ``3.0.23 Vetinari``."""

NOT_SET_UP: Final = "No VLC is set up on the Tools page."


class VlcLibrary:
    """python-vlc bound to one libvlc, or the reason it is not.

    Built by :meth:`load`, never directly. Every method is safe to call whatever the state: with no library there is no
    instance and no player, and :attr:`reason` says why. The ``vlc`` module itself is reachable through
    :attr:`module`, for the event and state enumerations a player needs, and is ``None`` when unavailable.

    :param module: the imported ``vlc`` module, or ``None``.
    :param library: the library it is bound to, or ``None``.
    :param reason: why there is none, or ``None`` when there is one.
    """

    def __init__(self, module: ModuleType | None, library: Path | None, reason: str | None) -> None:
        self.__module: Final = module
        self.__library: Final = library
        self.__reason: Final = reason

    @classmethod
    def unavailable(cls, reason: str) -> VlcLibrary:
        """A proxy with no library, for a reason the caller knows better than :meth:`load` would.

        :param reason: why there is none.
        :returns: the proxy, unavailable.
        """
        return cls(None, None, reason)

    @classmethod
    def load(cls, library: Path | None) -> VlcLibrary:
        """Import python-vlc bound to ``library``, or say why not; never raises.

        python-vlc binds its library when it is imported and cannot be rebound, so a second call with another path
        answers the library already bound, with a reason saying a restart is needed for the other.

        :param library: the ``libvlc`` shared library's full path, or ``None`` when none is set up.
        :returns: the proxy, available or not.
        """
        if library is None:
            return cls(None, None, NOT_SET_UP)
        bound = sys.modules.get("vlc")
        if bound is None:
            os.environ[LIBRARY_PATH_VARIABLE] = str(library)
            try:
                bound = importlib.import_module("vlc")
            except BaseException as error:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                # the import can raise anything, SystemExit included ([[appendices.vlc#python-vlc-import]])
                return cls(None, None, f"python-vlc could not load {library}: {cls.__describe(error)}")
        actual = cls.__bound_path(bound)
        if actual is None or os.path.normcase(str(actual)) != os.path.normcase(str(library)):
            return cls(None, None, f"python-vlc is bound to {actual} for this run; restart the app to use {library}.")
        return cls(bound, library, None)

    @property
    def available(self) -> bool:
        """Whether a libvlc is loaded and usable."""
        return self.__module is not None

    @property
    def reason(self) -> str | None:
        """Why no libvlc is usable, or ``None`` when one is."""
        return self.__reason

    @property
    def library(self) -> Path | None:
        """The library bound, or ``None``."""
        return self.__library

    @property
    def module(self) -> ModuleType | None:
        """The ``vlc`` module, for its ``EventType`` and ``State``; ``None`` when unavailable."""
        return self.__module

    @property
    def version(self) -> Version | None:
        """libvlc's version, or ``None`` when unavailable or unreadable."""
        if self.__module is None:
            return None
        text = self.__module.libvlc_get_version()
        match = VERSION_PATTERN.match(text.decode(errors="replace") if isinstance(text, bytes) else str(text))
        if match is None:
            return None
        return tuple(int(part) for part in match.groups() if part is not None)

    def instance(self, *options: str) -> Any | None:
        """A libvlc instance.

        :param options: libvlc's command-line options.
        :returns: the instance, or ``None`` when unavailable or when libvlc refuses an option, which it answers with
            ``None`` rather than an exception.
        """
        if self.__module is None:
            return None
        try:
            return self.__module.Instance(*options)
        except Exception:  # pylint: disable=broad-exception-caught  # a ctypes binding can raise anything
            LOG.warning("libvlc refused an instance.", exc_info=True)
            return None

    def media_player(self, instance: Any) -> Any | None:
        """A media player of an instance.

        :param instance: what :meth:`instance` returned.
        :returns: the player, or ``None`` when there is no instance or libvlc gives none.
        """
        if self.__module is None or instance is None:
            return None
        return instance.media_player_new() or None

    @staticmethod
    def __bound_path(module: ModuleType) -> Path | None:
        """The library a ``vlc`` module loaded.

        :param module: the module.
        :returns: the path its ``ctypes`` library carries, or ``None`` when it carries none.
        """
        name = getattr(getattr(module, "dll", None), "_name", None)
        return Path(name) if isinstance(name, str) and name else None

    @staticmethod
    def __describe(error: BaseException) -> str:
        """One line for what the import raised.

        :param error: what escaped the import.
        :returns: its type and, for anything but a bare exit, its message.
        """
        if isinstance(error, SystemExit):
            return f"it exited with {error.code}"
        return f"{type(error).__name__}: {error}"


def probe_libvlc(library: Path, output: Path) -> int:
    """Load a library the way the agent will, in this child process, and write what happened.

    :param library: the ``libvlc`` shared library.
    :param output: where to write the answer: a JSON object with ``status``, ``version``, ``reason`` and ``library``.
    :returns: the exit code: 0 once an answer was written.
    """
    loaded = VlcLibrary.load(library)
    version = loaded.version
    if not loaded.available:
        status, reason = ToolStatus.NOT_RUNNABLE, loaded.reason or ""
    elif loaded.instance() is None:
        status, reason = ToolStatus.NOT_RUNNABLE, "libvlc loaded but gave no instance."
    else:
        status, reason = ToolStatus.USABLE, ""
    output.write_text(
        json.dumps(
            {
                "status": status.value,
                "version": list(version or ()),
                "reason": reason,
                "library": str(loaded.library) if loaded.library is not None else "",
            }
        ),
        encoding="utf-8",
    )
    return 0
