"""Which of a copied selection's assets have a license text, asked of their disks off the GUI thread (#688,
[[assets#licenses]])."""

import itertools
import logging
import os
import threading
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Final

from PySide6.QtCore import QObject, Qt, Signal, Slot

from .copied_paths import CopiedPath, PathsWriter

LOG: Final = logging.getLogger(__name__)


class LicenseLookup(QObject):
    """Writes a copied selection with the license texts that are there, and answers on the GUI thread with the last one
    asked for.

    **It runs on a daemon thread** ([[appendices.code-conventions#worker-threads]]): the question goes to the assets'
    disks, and a share that went away blocks it for as long as a call takes, once per asset. Nothing may hold up
    quitting for that, so the thread is left behind; nothing arrives after :meth:`stop`.

    :param parent: optional Qt parent.
    """

    written: Signal = Signal(str)
    """Emitted on the GUI thread with the text of the last selection asked for."""

    __answered: Signal = Signal(int, str)
    """``(serial, text)``, emitted from a lookup's thread; its slot runs on the GUI thread, the connection queued."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__answered.connect(self.__on_answered, Qt.ConnectionType.QueuedConnection)
        self.__serials: Final = itertools.count(1)
        self.__asked = 0
        self.__stopped: Final = threading.Event()
        # a parent torn down without stop() must not be emitted into from a lookup's thread after its C++ object is
        # gone: ``set`` is a plain Python bound method, safe to run from here
        self.destroyed.connect(self.__stopped.set)

    def start(self, copied: Sequence[CopiedPath], write: PathsWriter) -> None:
        """Look for each resource's license text, then write the selection, outdating every lookup started before.

        :param copied: the resources, an asset's ``license`` the place its text would be.
        :param write: the format.
        """
        serial = self.__asked = next(self.__serials)
        threading.Thread(
            target=self.__run, args=(serial, tuple(copied), write), name=f"license-lookup-{serial}", daemon=True
        ).start()

    def discard(self) -> None:
        """Drop the answer of every lookup started so far, as a copy that needs none does."""
        self.__asked = next(self.__serials)

    def stop(self) -> None:
        """Deliver no more answers. A lookup still blocked on a share is not waited for."""
        self.__stopped.set()

    def __run(self, serial: int, copied: tuple[CopiedPath, ...], write: PathsWriter) -> None:
        """Look and write, and deliver the text unless stopped (a daemon thread).

        :param serial: the lookup.
        :param copied: the resources.
        :param write: the format.
        """
        try:
            text = write(tuple(self.__found(copied)))
        except Exception:  # pylint: disable=broad-exception-caught  # a thread's exception would only be printed
            LOG.exception("The paths could not be copied.")
            return
        if self.__stopped.is_set():
            return
        try:
            self.__answered.emit(serial, text)
        except RuntimeError:  # the lookup outlived its owner between the test and the emit
            pass

    def __found(self, copied: tuple[CopiedPath, ...]) -> Iterator[CopiedPath]:
        """The resources, each with its license text only where there is one; the rest unasked once stopped.

        :param copied: the resources.
        :returns: them, in order.
        """
        for item in copied:
            there = item.license is not None and not self.__stopped.is_set() and os.path.isfile(item.license)
            yield item if there else replace(item, license=None)

    @Slot(int, str)
    def __on_answered(self, serial: int, text: str) -> None:
        """Pass a lookup's text on, unless a later copy outdated it or the lookups were stopped (GUI thread).

        :param serial: the lookup.
        :param text: what it wrote.
        """
        if serial == self.__asked and not self.__stopped.is_set():
            self.written.emit(text)
