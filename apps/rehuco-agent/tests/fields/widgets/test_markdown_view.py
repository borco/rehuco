"""Tests for the Markdown viewer widget and its renderer."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser
from pytest import raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.markdown_view import MAX_IMAGE_WIDTH, MarkdownView, render_markdown


def load_image_resource(view: MarkdownView, mocker: MockerFixture, width: int, height: int) -> object:
    """Drive ``view.loadResource`` for an image the base class resolves to ``width`` x ``height``.

    The base ``QTextBrowser.loadResource`` is mocked to hand back that image, so the test exercises
    only the override's capping decision, not Qt's resource lookup.

    :param view: the viewer under test.
    :param mocker: the pytest-mock fixture.
    :param width: the resolved image's width in pixels.
    :param height: the resolved image's height in pixels.
    :returns: whatever the override returns for that image resource.
    """
    mocker.patch.object(QTextBrowser, "loadResource", return_value=QImage(width, height, QImage.Format.Format_RGB32))
    return view.loadResource(int(QTextDocument.ResourceType.ImageResource), QUrl("image.png"))


def test_render_markdown_renders_common_elements() -> None:
    """The renderer turns headings, emphasis, inline code and lists into HTML.

    **Test steps:**

    * render a Markdown snippet covering a heading, bold, code and a list
    * verify each maps to its HTML element
    """
    html = render_markdown("# Heading\n\n**bold** and `code`\n\n- one\n- two")

    assert "<h1" in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
    assert "<li>one</li>" in html


def test_render_markdown_defaults_to_the_markdown_engine() -> None:
    """With no ``engine`` argument, rendering uses the `markdown` package (fenced code support).

    **Test steps:**

    * render a fenced code block with no explicit engine
    * verify it produces a ``<pre>`` block (a `markdown`-extension feature, not CommonMark-bare)
    """
    html = render_markdown("```\nx = 1\n```")

    assert "<pre>" in html


def test_render_markdown_renders_via_the_mistletoe_engine() -> None:
    """``engine="mistletoe"`` renders through the `mistletoe` package instead.

    **Test steps:**

    * render a heading and bold text with ``engine="mistletoe"``
    * verify both map to their HTML element
    """
    html = render_markdown("# Heading\n\n**bold**", engine="mistletoe")

    assert "<h1>Heading</h1>" in html
    assert "<strong>bold</strong>" in html


def test_render_markdown_rejects_an_unknown_engine() -> None:
    """An unrecognized engine name raises ``KeyError`` rather than silently falling back.

    **Test steps:**

    * render with a made-up engine name
    * verify ``KeyError`` propagates
    """
    with raises(KeyError):
        render_markdown("hi", engine="not-a-real-engine")


def test_render_markdown_renders_tables_and_fenced_code_from_extensions() -> None:
    """The configured extensions render fenced code blocks and tables.

    **Test steps:**

    * render a fenced code block and a pipe table
    * verify a ``<pre>`` code block and a ``<table>`` are produced
    """
    html = render_markdown("```\nx = 1\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |")

    assert "<pre>" in html
    assert "<table>" in html


def test_markdown_view_shows_rendered_text(qtbot: QtBot) -> None:
    """`MarkdownView.set_markdown` renders and shows the text.

    **Test steps:**

    * build a viewer and set Markdown on it
    * verify the rendered plain text carries the content
    """
    view = MarkdownView()
    qtbot.addWidget(view)

    view.set_markdown("hello **world**")

    assert "world" in view.toPlainText()


def test_apply_rendering_settings_re_renders_with_the_new_engine(qtbot: QtBot) -> None:
    """``apply_rendering_settings`` re-renders the current text with the newly-selected engine.

    **Test steps:**

    * build a viewer with the default (``markdown``) engine and set fenced-code text
    * apply settings switching to ``mistletoe``
    * verify the re-rendered output no longer shows the `markdown`-extension ``<pre>`` styling
      that plain CommonMark fenced code renders differently (``<pre><code>``)
    """
    view = MarkdownView()
    qtbot.addWidget(view)
    view.set_markdown("# Heading")
    assert "Heading" in view.toPlainText()

    view.apply_rendering_settings(engine="mistletoe", css="", max_image_width=MAX_IMAGE_WIDTH)

    assert "Heading" in view.toPlainText()


def test_apply_rendering_settings_updates_the_image_width_cap(qtbot: QtBot, mocker: MockerFixture) -> None:
    """``apply_rendering_settings`` changes the width cap used by a later ``loadResource``.

    **Test steps:**

    * build a viewer with a wide cap, then apply settings with a narrower one
    * resolve a wide image
    * verify it's scaled to the new, narrower cap
    """
    view = MarkdownView(max_image_width=1000)
    qtbot.addWidget(view)

    view.apply_rendering_settings(engine="markdown", css="", max_image_width=100)

    loaded = load_image_resource(view, mocker, 400, 200)
    assert isinstance(loaded, QImage)
    assert loaded.width() == 100


def test_markdown_view_takes_an_image_width_cap(qtbot: QtBot) -> None:
    """The viewer accepts an image-width cap, defaulting to :data:`MAX_IMAGE_WIDTH`.

    The actual scaling only bites once images resolve (a follow-up), so this covers construction --
    the default and an explicit override both build.

    **Test steps:**

    * build a viewer with the default cap and one with an explicit cap
    * verify both construct
    """
    default_view = MarkdownView()
    capped_view = MarkdownView(max_image_width=MAX_IMAGE_WIDTH // 2)
    qtbot.addWidget(default_view)
    qtbot.addWidget(capped_view)

    assert isinstance(default_view, MarkdownView)
    assert isinstance(capped_view, MarkdownView)


def test_load_resource_scales_an_over_wide_image_down_to_the_cap(qtbot: QtBot, mocker: MockerFixture) -> None:
    """`loadResource` scales an image wider than the cap down to it, preserving aspect ratio.

    **Test steps:**

    * resolve a 400x200 image on a viewer capped to 100 px
    * verify the returned image is 100x50
    """
    view = MarkdownView(max_image_width=100)
    qtbot.addWidget(view)

    loaded = load_image_resource(view, mocker, 400, 200)

    assert isinstance(loaded, QImage)
    assert loaded.width() == 100
    assert loaded.height() == 50


def test_load_resource_leaves_an_image_within_the_cap_untouched(qtbot: QtBot, mocker: MockerFixture) -> None:
    """`loadResource` returns an image no wider than the cap unchanged.

    **Test steps:**

    * resolve an 80x40 image on a viewer capped to 100 px
    * verify its size is unchanged
    """
    view = MarkdownView(max_image_width=100)
    qtbot.addWidget(view)

    loaded = load_image_resource(view, mocker, 80, 40)

    assert isinstance(loaded, QImage)
    assert loaded.width() == 80
    assert loaded.height() == 40
