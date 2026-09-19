"""Asks before a delete the Recycle Bin cannot take is skipped instead of failing silently or failing
the job (#301).

Wraps whatever `~rehuco_core.Deleter` a caller would otherwise use -- typically `configured_deleter`'s
answer -- and offers a permanent delete for the files a Recycle-Bin-capable deleter refuses
(`~rehuco_core.NoTrashBinError`), the question the images dock already asked before this brought
Convert, Discard Originals and the document's inline Discard Backups into line with it.

**One question per operation, not per file.** Whether a bin is reachable is a property of a location,
and every file one operation deletes sits in the same directory -- so the first refusal already answers
for the rest. The question therefore names the whole set up front, and the answer sticks for the
instance's life: declining once is not asked again on the next file either.

Top-level rather than under ``documents``: the images dock (``fields/widgets``) is one of its callers,
and the field toolkit may not import ``documents`` ([[plugins#field-toolkit]]).
"""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from PySide6.QtWidgets import QMessageBox, QWidget
from rehuco_core import DEFAULT_DELETER, Deleter, NoTrashBinError

LOG: Final = logging.getLogger(__name__)

TITLE: Final = "No Recycle Bin available"


class AskingDeleter:  # pylint: disable=too-few-public-methods
    """A `~rehuco_core.Deleter` that asks, once per operation, when `inner` refuses with
    `~rehuco_core.NoTrashBinError` (#301).

    The refusal is the one point a bin-first delete turns permanent, so this question is that kind of
    file's permanent-delete confirmation, and the same *without asking* box that would skip the up-front
    one silences it: nothing is asked while `without_asking` is set, and every refusal then deletes
    permanently outright (#312 -- which box applies is the caller's to say, since only it knows what
    kind of file the operation is deleting).

    :param inner: the deleter tried first -- typically `configured_deleter`'s answer.
    :param parent: the widget a confirmation (and, if `report_delete_failures`, a failure notice) is
        shown over.
    :param files: every file this operation will delete, listed in the question so the answer is given
        knowing its whole reach; empty lists only the file that was refused.
    :param report_delete_failures: whether a non-bin `OSError` from `inner` is shown to the user, with
        its own message box, before being re-raised -- off by default, since convert and the inline
        Discard Backups action already have their own handling for a genuine failure; the images dock
        turns this on, because its own caller (`RehuDocumentImageOrganizer.remove`) cannot otherwise
        tell a delete failure from the renumbering failure that follows it, and the renumbering failure
        must stay silent.
    :param without_asking: whether a refusal deletes permanently with no question -- the operation's
        own **Clear backups without asking** / **Delete images without asking** box.
    """

    def __init__(
        self,
        inner: Deleter,
        parent: QWidget | None = None,
        *,
        files: Sequence[Path] = (),
        report_delete_failures: bool = False,
        without_asking: bool = False,
    ) -> None:
        self.__inner: Final = inner
        self.__parent: Final = parent
        self.__files: Final = tuple(files)
        self.__report_delete_failures: Final = report_delete_failures
        self.__without_asking: Final = without_asking
        self.__delete_permanently: bool | None = None

    def delete(self, path: Path) -> None:
        """Remove ``path`` through `inner`, asking if it refuses with `NoTrashBinError`.

        :param path: the file to delete.
        :raises NoTrashBinError: `inner` refused and this operation's answer -- given now, or on an
            earlier file -- was No.
        :raises OSError: `inner` or the permanent fallback failed for a reason other than a missing
            bin; reported first, if `report_delete_failures`, then re-raised either way.
        """
        try:
            self.__inner.delete(path)
        except NoTrashBinError as error:
            if not self.__permanent_delete_allowed(path, error):
                raise
        except OSError as error:
            self.__report(path, error)
            raise
        else:
            return
        # outside the handler above on purpose: an exception raised inside an `except` block is not
        # routed to its sibling clauses, so a fallback that fails here would otherwise go unreported
        try:
            DEFAULT_DELETER.delete(path)
        except OSError as error:
            self.__report(path, error)
            raise

    def __permanent_delete_allowed(self, path: Path, error: NoTrashBinError) -> bool:
        if self.__without_asking:
            return True
        if self.__delete_permanently is None:
            self.__delete_permanently = self.__ask(path, error)
        return self.__delete_permanently

    def __ask(self, path: Path, error: NoTrashBinError) -> bool:
        files = self.__files or (path,)
        listed = "<br>".join(f"&nbsp;&nbsp;{file.name}" for file in files)
        what = f"<b>{files[0].name}</b>" if len(files) == 1 else f"these <b>{len(files)} files</b>"
        text = f"{error}<br><br>Delete {what} permanently instead? This cannot be undone.<br><br>{listed}"
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        answer = QMessageBox.question(self.__parent, TITLE, text, buttons, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def __report(self, path: Path, error: OSError) -> None:
        # a file already gone is a rescan, not a failure -- `RecycleBinDeleter` passes it through
        # unwrapped for the same reason (#298), and the caller's rebuild is the right answer to it
        if not self.__report_delete_failures or isinstance(error, FileNotFoundError):
            return
        LOG.error("Could not delete %s: %s", path, error)
        QMessageBox.critical(self.__parent, "Could Not Delete", f"{path.name} could not be deleted:\n\n{error}")
