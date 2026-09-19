"""Tests for the one permanent-delete confirmation and its *without asking* box (#313).

The box is a constructed `QMessageBox` rather than a static call, so ``QMessageBox.exec`` is replaced
with a plain function on the class -- bound as a method, it receives the box itself, which is what a
test needs to tick the checkbox and read what the box shows. A ``MagicMock`` there would swallow
``self``.
"""

from collections.abc import Callable, Iterator
from typing import Any, Final

from PySide6.QtWidgets import QMessageBox, QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.delete_confirmation import ask_permanent_delete, confirm_delete
from rehuco_agent.settings import deletion_settings
from rehuco_agent.settings.deletion_settings import (
    WITHOUT_ASKING_BOXES,
    DeletionKind,
    DeletionSettings,
    shared_deletion_settings,
)

TITLE: Final = "Delete screenshot"
TEXT: Final = "Delete <b>info03.jpg</b> from this resource?"


# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value  # pylint: disable=unsupported-assignment-operation

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


class ShownBox:  # pylint: disable=too-few-public-methods
    """What one ``exec`` saw of the box it was called on, and how it answered."""

    def __init__(self, *, answer: QMessageBox.StandardButton, tick: bool) -> None:
        self.answer: Final = answer
        self.tick: Final = tick
        self.shown: list[QMessageBox] = []

    def exec(self, box: QMessageBox) -> int:
        """Stand in for ``QMessageBox.exec``: record the box, tick it as asked, answer as asked."""
        self.shown.append(box)
        check_box = box.checkBox()
        assert check_box is not None
        check_box.setChecked(self.tick)
        return int(self.answer)


@fixture(name="parent")
def fixture_parent(qtbot: QtBot) -> QWidget:
    """A real widget for the box to be shown over."""
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


@fixture(name="store", autouse=True)
def fixture_store(mocker: MockerFixture) -> FakeSettings:
    """The persistent store a ticked box is saved into, patched where `remember_without_asking` reaches
    it -- the same seam ``conftest.py`` isolates, re-patched here so the test holds the instance and
    can read what was written.

    :param mocker: pytest-mock fixture.
    :returns: the in-memory store.
    """
    store = FakeSettings()
    mocker.patch.object(deletion_settings, "persistent_settings", return_value=store)
    return store


@fixture(name="permanent")
def fixture_permanent() -> Iterator[None]:
    """The Recycle Bin off, so an up-front confirm is actually put; ``conftest.py`` already hands
    every test an isolated `DeletionSettings`."""
    shared_deletion_settings().use_recycle_bin = False
    yield


@fixture(name="show")
def fixture_show(mocker: MockerFixture) -> Callable[[QMessageBox.StandardButton, bool], ShownBox]:
    """Install a stand-in ``exec`` that answers and ticks as a test asks.

    :param mocker: pytest-mock fixture.
    :returns: a callable installing the stand-in and returning it, for reading what was shown.
    """

    def install(answer: QMessageBox.StandardButton, tick: bool = False) -> ShownBox:
        stand_in = ShownBox(answer=answer, tick=tick)

        # a plain function, not the bound method: only a function set on the class is rebound with
        # the box as its first argument when ``box.exec()`` is called
        def exec_(box: QMessageBox) -> int:
            return stand_in.exec(box)

        mocker.patch.object(QMessageBox, "exec", exec_)
        return stand_in

    return install


def persisted(store: FakeSettings) -> DeletionSettings:
    """What the persistent store holds now, loaded fresh."""
    settings = DeletionSettings()
    settings.load(store)  # type: ignore[arg-type]
    return settings


# region confirm_delete: the gate


@mark.usefixtures("permanent")
def test_a_permanent_delete_is_asked_about_with_the_kinds_box(parent: QWidget, show: Callable[..., ShownBox]) -> None:
    """With the bin off and the box unticked, the question is put -- titled and worded as the caller
    asked, defaulting to No, with the kind's own box on it, worded as the Files page words it.

    **Test steps:**

    * confirm an images delete with the bin off, answering Yes
    * verify one box was shown carrying the title, the text, the No default and the verbatim label
    """
    shown = show(QMessageBox.StandardButton.Yes)

    assert confirm_delete(parent, DeletionKind.IMAGES, TITLE, TEXT) is True

    (box,) = shown.shown
    assert box.windowTitle() == TITLE
    assert box.text() == TEXT
    assert box.defaultButton() == box.button(QMessageBox.StandardButton.No)
    check_box = box.checkBox()
    assert check_box is not None
    assert check_box.text() == WITHOUT_ASKING_BOXES[DeletionKind.IMAGES].label


@mark.usefixtures("permanent")
def test_no_refuses(parent: QWidget, show: Callable[..., ShownBox]) -> None:
    """No is No.

    **Test steps:**

    * confirm with the bin off, answering No
    * verify the refusal
    """
    show(QMessageBox.StandardButton.No)

    assert confirm_delete(parent, DeletionKind.IMAGES, TITLE, TEXT) is False


def test_a_delete_bound_for_the_recycle_bin_asks_nothing(parent: QWidget, show: Callable[..., ShownBox]) -> None:
    """The bin on (the default) means the delete is not permanent, so there is nothing to confirm.

    **Test steps:**

    * confirm with the bin on
    * verify it went ahead and no box was shown
    """
    shown = show(QMessageBox.StandardButton.No)

    assert confirm_delete(parent, DeletionKind.BACKUPS, TITLE, TEXT) is True

    assert not shown.shown


@mark.usefixtures("permanent")
@mark.parametrize("kind", list(DeletionKind))
def test_a_ticked_box_silences_its_own_kind_only(
    parent: QWidget, show: Callable[..., ShownBox], kind: DeletionKind
) -> None:
    """Each box silences the confirmations of its own kind of file, and not the other's.

    **Test steps:**

    * tick one kind's box on the shared settings, with the bin off
    * confirm a delete of that kind, then of the other
    * verify the first asked nothing and the second was asked
    """
    shown = show(QMessageBox.StandardButton.No)
    shared_deletion_settings().set_without_asking(kind, True)
    other = next(candidate for candidate in DeletionKind if candidate is not kind)

    assert confirm_delete(parent, kind, TITLE, TEXT) is True
    assert not shown.shown

    assert confirm_delete(parent, other, TITLE, TEXT) is False
    assert len(shown.shown) == 1


# endregion

# region the box: applied only on Yes


@mark.usefixtures("permanent")
def test_yes_with_the_box_ticked_writes_the_kinds_flag_and_saves_it(
    parent: QWidget, show: Callable[..., ShownBox], store: FakeSettings
) -> None:
    """Tick + Yes is the Files page's own box being ticked: the shared settings hold it and it is
    persisted, so the next delete of that kind asks nothing and neither does the next launch.

    **Test steps:**

    * confirm a backups delete with the box ticked and Yes
    * verify the shared flag is on, the store holds it, the other flag is untouched, and a second
      confirm of the same kind asks nothing
    """
    shown = show(QMessageBox.StandardButton.Yes, tick=True)

    assert confirm_delete(parent, DeletionKind.BACKUPS, TITLE, TEXT) is True

    assert shared_deletion_settings().clear_backups_without_asking is True
    assert persisted(store).clear_backups_without_asking is True
    assert persisted(store).delete_images_without_asking is False
    assert confirm_delete(parent, DeletionKind.BACKUPS, TITLE, TEXT) is True
    assert len(shown.shown) == 1


@mark.usefixtures("permanent")
def test_yes_with_the_box_unticked_writes_nothing(
    parent: QWidget, show: Callable[..., ShownBox], store: FakeSettings
) -> None:
    """A plain Yes is a one-off: the next delete asks again.

    **Test steps:**

    * confirm twice with the box unticked and Yes
    * verify nothing was written and both were asked
    """
    shown = show(QMessageBox.StandardButton.Yes)

    assert confirm_delete(parent, DeletionKind.BACKUPS, TITLE, TEXT) is True
    assert confirm_delete(parent, DeletionKind.BACKUPS, TITLE, TEXT) is True

    assert shared_deletion_settings().clear_backups_without_asking is False
    assert persisted(store).clear_backups_without_asking is False
    assert len(shown.shown) == 2


@mark.usefixtures("permanent")
def test_no_with_the_box_ticked_writes_nothing_and_asks_next_time(
    parent: QWidget, show: Callable[..., ShownBox], store: FakeSettings
) -> None:
    """Tick + No saves nothing: a No with "don't ask" would mean *never delete*, which the flag
    cannot express, so the tick is dropped and the next delete is asked about again.

    **Test steps:**

    * confirm with the box ticked and No, then again
    * verify both refused, nothing was written, and both were asked
    """
    shown = show(QMessageBox.StandardButton.No, tick=True)

    assert confirm_delete(parent, DeletionKind.IMAGES, TITLE, TEXT) is False
    assert confirm_delete(parent, DeletionKind.IMAGES, TITLE, TEXT) is False

    assert shared_deletion_settings().delete_images_without_asking is False
    assert persisted(store).delete_images_without_asking is False
    assert len(shown.shown) == 2


# endregion

# region ask_permanent_delete: the question on its own


def test_ask_permanent_delete_is_put_whatever_the_gate_would_say(
    parent: QWidget, show: Callable[..., ShownBox]
) -> None:
    """The refusal-point question is put with the bin on -- that is the point where a bin-bound delete
    has just turned permanent, and the gating is the caller's.

    **Test steps:**

    * ask, with the bin on (the default), answering Yes with the box ticked
    * verify the box was shown and the tick was applied
    """
    shown = show(QMessageBox.StandardButton.Yes, tick=True)

    assert ask_permanent_delete(parent, DeletionKind.IMAGES, TITLE, TEXT) is True

    assert len(shown.shown) == 1
    assert shared_deletion_settings().delete_images_without_asking is True


# endregion
