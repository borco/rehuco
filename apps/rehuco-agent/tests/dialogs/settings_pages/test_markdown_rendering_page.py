"""Tests for MarkdownRenderingPage: the Markdown-rendering settings category page (#26, #47)."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.settings_pages import markdown_rendering_page
from rehuco_agent.dialogs.settings_pages.markdown_rendering_page import MarkdownRenderingPage
from rehuco_agent.settings import markdown_rendering_settings
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings


# region fixtures
# Mirrors test_markdown_rendering_settings.py's (and conftest.py's) FakeSettings exactly -- kept as
# a separate copy rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module
    (used by :func:`shared_markdown_rendering_settings`'s lazy load) and the page module itself
    (used by :meth:`MarkdownRenderingPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(markdown_rendering_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the shared settings singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_markdown_rendering_settings.cache_clear()
    yield
    shared_markdown_rendering_settings.cache_clear()


# endregion


def test_starts_with_the_shared_settings_current_values(qtbot: QtBot) -> None:
    """A freshly-built page's fields reflect the shared settings' current values.

    **Test steps:**

    * seed the shared settings with non-default values
    * build the page
    * verify each field shows the seeded value
    """
    settings = shared_markdown_rendering_settings()
    settings.engine = "mistletoe"
    settings.markdown_css = "markdown-css"
    settings.mistletoe_css = "mistletoe-css"
    settings.max_image_width = 500

    page = MarkdownRenderingPage()
    qtbot.addWidget(page)

    ui = page._MarkdownRenderingPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.mistletoe_engine_radio_button.isChecked()
    assert ui.css_edit.toPlainText() == "mistletoe-css"
    assert ui.max_image_width_spin_box.value() == 500


def test_switching_engine_shows_the_other_engines_css_draft(qtbot: QtBot) -> None:
    """Switching the engine radio swaps the CSS editor to that engine's own draft.

    **Test steps:**

    * seed distinct CSS for both engines (starting on markdown)
    * build the page and switch to mistletoe
    * verify the editor now shows the mistletoe CSS
    * switch back to markdown
    * verify the editor shows the markdown CSS again
    """
    settings = shared_markdown_rendering_settings()
    settings.markdown_css = "markdown-css"
    settings.mistletoe_css = "mistletoe-css"

    page = MarkdownRenderingPage()
    qtbot.addWidget(page)
    ui = page._MarkdownRenderingPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.mistletoe_engine_radio_button.setChecked(True)
    assert ui.css_edit.toPlainText() == "mistletoe-css"

    ui.markdown_engine_radio_button.setChecked(True)
    assert ui.css_edit.toPlainText() == "markdown-css"


def test_editing_css_preserves_the_other_engines_draft(qtbot: QtBot) -> None:
    """Editing one engine's CSS doesn't disturb the other engine's already-staged draft.

    **Test steps:**

    * build the page, edit the markdown CSS, switch to mistletoe and edit its CSS too
    * switch back to markdown
    * verify the markdown edit survived
    """
    page = MarkdownRenderingPage()
    qtbot.addWidget(page)
    ui = page._MarkdownRenderingPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.css_edit.setPlainText("edited-markdown-css")
    ui.mistletoe_engine_radio_button.setChecked(True)
    ui.css_edit.setPlainText("edited-mistletoe-css")

    ui.markdown_engine_radio_button.setChecked(True)

    assert ui.css_edit.toPlainText() == "edited-markdown-css"


def test_is_dirty_is_false_right_after_construction(qtbot: QtBot) -> None:
    """A freshly-built page (nothing edited yet) is not dirty.

    **Test steps:**

    * build the page
    * verify ``is_dirty`` is ``False``
    """
    page = MarkdownRenderingPage()
    qtbot.addWidget(page)

    assert page.is_dirty() is False


def test_is_dirty_is_true_after_an_edit(qtbot: QtBot) -> None:
    """Editing any field makes the page dirty.

    **Test steps:**

    * build the page and change the image-width spin box
    * verify ``is_dirty`` is ``True``
    """
    page = MarkdownRenderingPage()
    qtbot.addWidget(page)
    ui = page._MarkdownRenderingPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.max_image_width_spin_box.setValue(999)

    assert page.is_dirty() is True


def test_save_changes_updates_the_shared_settings_and_persists(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` pushes every staged field into the shared settings object and persists it.

    **Test steps:**

    * build the page, switch engine, edit CSS, change the width cap
    * call ``save_changes``
    * verify the shared settings object reflects every change
    * verify a fresh load from the persisted store reflects them too
    """
    page = MarkdownRenderingPage()
    qtbot.addWidget(page)
    ui = page._MarkdownRenderingPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.mistletoe_engine_radio_button.setChecked(True)
    ui.css_edit.setPlainText("new-mistletoe-css")
    ui.max_image_width_spin_box.setValue(777)

    page.save_changes()

    settings = shared_markdown_rendering_settings()
    assert settings.engine == "mistletoe"
    assert settings.mistletoe_css == "new-mistletoe-css"
    assert settings.max_image_width == 777

    reloaded = type(settings)()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.engine == "mistletoe"
    assert reloaded.mistletoe_css == "new-mistletoe-css"
    assert reloaded.max_image_width == 777


def test_save_changes_clears_dirty(qtbot: QtBot) -> None:
    """After ``save_changes``, the page is no longer dirty.

    **Test steps:**

    * build the page, edit a field, save
    * verify ``is_dirty`` is now ``False``
    """
    page = MarkdownRenderingPage()
    qtbot.addWidget(page)
    ui = page._MarkdownRenderingPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.max_image_width_spin_box.setValue(999)

    page.save_changes()

    assert page.is_dirty() is False


def test_drop_changes_reverts_edits(qtbot: QtBot) -> None:
    """``drop_changes`` reverts every field back to the shared settings' current values.

    **Test steps:**

    * build the page and edit every field
    * call ``drop_changes``
    * verify every field is back to the (unsaved, still-default) shared settings values
    """
    page = MarkdownRenderingPage()
    qtbot.addWidget(page)
    ui = page._MarkdownRenderingPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.mistletoe_engine_radio_button.setChecked(True)
    ui.css_edit.setPlainText("unsaved-css")
    ui.max_image_width_spin_box.setValue(999)

    page.drop_changes()

    assert ui.markdown_engine_radio_button.isChecked()
    assert ui.css_edit.toPlainText() == ""
    assert ui.max_image_width_spin_box.value() == shared_markdown_rendering_settings().max_image_width
    assert page.is_dirty() is False


def test_title_is_markdown_rendering(qtbot: QtBot) -> None:
    """The page's category-tree title is "Markdown Rendering".

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page = MarkdownRenderingPage()
    qtbot.addWidget(page)

    assert page.title == "Markdown Rendering"


def test_field_labels_lists_the_settings(qtbot: QtBot) -> None:
    """The page reports its setting labels for the settings dialog's filter box.

    **Test steps:**

    * construct the page
    * verify ``field_labels`` includes the key terms
    """
    page = MarkdownRenderingPage()
    qtbot.addWidget(page)

    labels = page.field_labels()
    assert "markdown" in labels
    assert "mistletoe" in labels
    assert "CSS" in labels
    assert "Maximum image width" in labels
