"""Tests for ThemeModel."""

from borco_pyside.theming.theme_model import ThemeModel
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication
from pytest_mock import MockerFixture


def test_defaults_to_the_follow_system_mode(mocker: MockerFixture) -> None:
    """With no explicit ``mode``, a freshly-constructed model defaults to ``Unknown`` (follow
    system) and applies it.

    **Test steps:**

    * spy on QStyleHints.setColorScheme
    * construct a ThemeModel with no ``mode`` argument
    * verify ``mode`` is ``Unknown`` and it was applied
    """
    set_scheme = mocker.patch.object(QApplication.styleHints(), "setColorScheme")

    model = ThemeModel()

    assert model.mode == Qt.ColorScheme.Unknown
    set_scheme.assert_called_once_with(Qt.ColorScheme.Unknown)


def test_applies_an_explicit_initial_mode_on_construction(mocker: MockerFixture) -> None:
    """An explicit initial ``mode`` (e.g. a persisted choice restored on launch) is applied
    immediately on construction.

    **Test steps:**

    * spy on QStyleHints.setColorScheme
    * construct a ThemeModel with ``mode=Dark``
    * verify ``mode`` is ``Dark`` and it was applied
    """
    set_scheme = mocker.patch.object(QApplication.styleHints(), "setColorScheme")

    model = ThemeModel(Qt.ColorScheme.Dark)

    assert model.mode == Qt.ColorScheme.Dark
    set_scheme.assert_called_once_with(Qt.ColorScheme.Dark)


def test_setting_mode_applies_it_and_emits_mode_changed(mocker: MockerFixture) -> None:
    """Setting ``mode`` to a new value applies it via QStyleHints and emits ``mode_changed``.

    **Test steps:**

    * construct a ThemeModel and connect a slot to mode_changed
    * set ``mode`` to Light
    * verify the new scheme was applied and the signal fired with the new mode
    """
    mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    model = ThemeModel()
    on_changed = mocker.Mock()
    model.mode_changed.connect(on_changed)
    set_scheme = mocker.patch.object(QApplication.styleHints(), "setColorScheme")

    model.mode = Qt.ColorScheme.Light

    assert model.mode == Qt.ColorScheme.Light
    set_scheme.assert_called_once_with(Qt.ColorScheme.Light)
    on_changed.assert_called_once_with(Qt.ColorScheme.Light)


def test_setting_the_same_mode_is_a_no_op(mocker: MockerFixture) -> None:
    """Setting ``mode`` to its own current value applies nothing and emits nothing.

    **Test steps:**

    * construct a ThemeModel already in Dark, then reset the spies
    * set ``mode`` to Dark again
    * verify neither QStyleHints nor mode_changed fired
    """
    mocker.patch.object(QApplication.styleHints(), "setColorScheme")
    model = ThemeModel(Qt.ColorScheme.Dark)
    on_changed = mocker.Mock()
    model.mode_changed.connect(on_changed)
    set_scheme = mocker.patch.object(QApplication.styleHints(), "setColorScheme")

    model.mode = Qt.ColorScheme.Dark

    set_scheme.assert_not_called()
    on_changed.assert_not_called()


def test_defaults_to_no_parent() -> None:
    """With no explicit parent, the model has none.

    **Test steps:**

    * construct a ThemeModel with no `parent` argument
    * verify it has no Qt parent
    """
    model = ThemeModel()

    assert model.parent() is None


def test_accepts_an_explicit_parent() -> None:
    """An explicit `parent` argument parents the model to it.

    **Test steps:**

    * construct a ThemeModel with an explicit parent
    * verify its Qt parent is that object
    """
    parent = QObject()

    model = ThemeModel(parent=parent)

    assert model.parent() is parent
