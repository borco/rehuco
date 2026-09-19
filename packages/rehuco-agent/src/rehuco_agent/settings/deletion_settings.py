"""The one deletion policy every user-facing delete in the app answers to (#291, #298, #312, #313).

A plain ``@dataclass``, like `ReferenceImagesSettings`: this is read once, at the moment a delete is
about to happen -- there is nothing already on screen for an Apply to update, so it earns no
``SimpleProperty`` reactivity.

The two *without asking* boxes are addressed by :class:`DeletionKind` rather than by name: a
permanent-delete confirmation carries the box for its kind of file (#313), so the flag it writes and
the label it shows must never drift apart -- :data:`WITHOUT_ASKING_BOXES` pairs them in one table,
beside the settings it names.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "screenshot_deletion"
"""Named for the setting's first consumer, the images dock's delete (#291), and deliberately kept when
the object was renamed for what it now gates (#312): the one value that predates the rename,
:data:`USE_RECYCLE_BIN_KEY`, maps onto the same box unchanged, and a new group name would buy nothing
but a migration for it."""

CLEAR_BACKUPS_WITHOUT_ASKING_KEY: Final = "clear_backups_without_asking"
DELETE_IMAGES_WITHOUT_ASKING_KEY: Final = "delete_images_without_asking"
USE_RECYCLE_BIN_KEY: Final = "use_recycle_bin"

DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING: Final = False
"""Whether a fresh install permanently deletes ``.orig`` conversion backups without a question. Off:
asking before the one irreversible step in the import flow is the safer default."""

DEFAULT_DELETE_IMAGES_WITHOUT_ASKING: Final = False
"""Whether a fresh install permanently deletes a screenshot without a question. Off, for the same
reason as :data:`DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING`."""

DEFAULT_USE_RECYCLE_BIN: Final = True
"""Whether a fresh install (no ``.ini`` yet) sends a deleted file to the Recycle Bin / Trash. On:
the safer default -- a permanent delete is the deliberate exception (#291), not the everyday case."""


class DeletionKind(StrEnum):
    """What kind of file a permanent delete is about -- which *without asking* box it answers to (#313).

    An enum rather than a callable or a flag name, because it pairs two things that must not drift:
    which `DeletionSettings` field to write, and what the confirmation's checkbox says. The pairing
    is :data:`WITHOUT_ASKING_BOXES`, not the members.
    """

    BACKUPS = "backups"
    """A conversion's ``.orig`` backups -- Convert, Discard Originals, the inline Discard Backups
    action, the bulk backups dialog."""

    IMAGES = "images"
    """A screenshot deleted from the images dock."""


@dataclass(frozen=True)
class WithoutAskingBox:
    """One *without asking* box: what it says on the Files page, and where `DeletionSettings` keeps it.

    :ivar label: the box's text, **verbatim** -- a confirmation shows the same words, so the user
        knows which box on Files unticks what they just ticked (#313).
    :ivar field: the `DeletionSettings` attribute the box stages.
    """

    label: str
    field: str


WITHOUT_ASKING_BOXES: Final[Mapping[DeletionKind, WithoutAskingBox]] = {
    DeletionKind.BACKUPS: WithoutAskingBox("Clear backups without asking", "clear_backups_without_asking"),
    DeletionKind.IMAGES: WithoutAskingBox("Delete images without asking", "delete_images_without_asking"),
}
"""The one table pairing each `DeletionKind` with its box (#313). The labels are the Files page's
own, and its test pins the two together."""


@dataclass
class DeletionSettings:
    """How a file this app removes on the user's behalf is deleted, and whether that is asked about
    first (#291, #298, #312).

    One policy, three boxes on the Files page. A question is only ever asked for a **permanent**
    delete: while :attr:`use_recycle_bin` is on and a bin is reachable for the file, it goes there with
    no question at all, whatever the other two say. A permanent delete -- up front while
    :attr:`use_recycle_bin` is off, or as the fallback when the bin turned out to be unreachable
    (`~rehuco_agent.asking_deleter.AskingDeleter`) -- asks unless the box for that kind of file says
    not to: :attr:`clear_backups_without_asking` for a conversion's ``.orig`` backups,
    :attr:`delete_images_without_asking` for a screenshot. The question itself carries that box
    (`~rehuco_agent.delete_confirmation`, #313), so it can be ticked at the moment it matters.

    First written for the images dock's delete alone; `~rehuco_agent.recycle_bin_deleter.configured_deleter`
    -- the one place :attr:`use_recycle_bin` is read -- is now also what a legacy-``.tc`` conversion's
    discarded backup and both conversion-backups discard surfaces resolve into a `RecycleBinDeleter` or
    `~rehuco_core.DEFAULT_DELETER`, absent a caller's own explicit choice.
    """

    clear_backups_without_asking: bool = DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING
    """Whether a permanent delete of ``.orig`` conversion backups -- Convert, Discard Originals, the
    inline Discard Backups action, the bulk backups dialog -- happens without a question."""

    delete_images_without_asking: bool = DEFAULT_DELETE_IMAGES_WITHOUT_ASKING
    """Whether a permanent delete of a screenshot from the images dock happens without a question."""

    use_recycle_bin: bool = DEFAULT_USE_RECYCLE_BIN
    """Whether a deleted file goes to the Recycle Bin / Trash when one is reachable for it, rather than
    being unlinked outright."""

    def without_asking(self, kind: DeletionKind) -> bool:
        """Whether a permanent delete of ``kind`` happens with no question -- that kind's box (#313).

        :param kind: what kind of file is being deleted.
        :returns: the box's value.
        """
        return cast(bool, getattr(self, WITHOUT_ASKING_BOXES[kind].field))

    def set_without_asking(self, kind: DeletionKind, value: bool) -> None:
        """Tick or untick ``kind``'s box -- what a confirmation's own checkbox writes (#313).

        :param kind: what kind of file is being deleted.
        :param value: the box's new value.
        """
        setattr(self, WITHOUT_ASKING_BOXES[kind].field, value)

    def load(self, settings: QSettings) -> None:
        """Replace the current choice with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.clear_backups_without_asking = cast(
            bool,
            settings.value(CLEAR_BACKUPS_WITHOUT_ASKING_KEY, DEFAULT_CLEAR_BACKUPS_WITHOUT_ASKING, type=bool),
        )
        self.delete_images_without_asking = cast(
            bool,
            settings.value(DELETE_IMAGES_WITHOUT_ASKING_KEY, DEFAULT_DELETE_IMAGES_WITHOUT_ASKING, type=bool),
        )
        self.use_recycle_bin = cast(bool, settings.value(USE_RECYCLE_BIN_KEY, DEFAULT_USE_RECYCLE_BIN, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current choice to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(CLEAR_BACKUPS_WITHOUT_ASKING_KEY, self.clear_backups_without_asking)
        settings.setValue(DELETE_IMAGES_WITHOUT_ASKING_KEY, self.delete_images_without_asking)
        settings.setValue(USE_RECYCLE_BIN_KEY, self.use_recycle_bin)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_deletion_settings() -> DeletionSettings:
    """The single, process-wide `DeletionSettings` instance, loaded from persistent storage on first
    call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.identity_settings.shared_identity_settings`: the settings page's Save
    must be what the next delete reads, not a disconnected per-reader copy.

    :returns: the shared instance.
    """
    settings = DeletionSettings()
    settings.load(persistent_settings())
    return settings


def remember_without_asking(kind: DeletionKind) -> None:
    """Tick ``kind``'s box on the shared settings and persist it -- what a permanent-delete
    confirmation does when its checkbox was ticked and the answer was Yes (#313).

    Nothing new is stored: the lifetime is the setting's, and the reset is unticking the same box on
    the Files page. Written here rather than by the confirmation because this module is where the
    shared instance and its persistent store are known.

    :param kind: what kind of file the box is about.
    """
    settings = shared_deletion_settings()
    settings.set_without_asking(kind, True)
    settings.save(persistent_settings())
