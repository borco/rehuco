"""Tests for the Markdown viewer widget and its renderer."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser
from pytest import raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.markdown_view import MarkdownView, render_markdown


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

    view.apply_rendering_settings(engine="mistletoe", css="")

    assert "Heading" in view.toPlainText()


def test_load_resource_uses_the_image_scanner_when_it_resolves_the_name(qtbot: QtBot, mocker: MockerFixture) -> None:
    """`loadResource` returns the ``ImageScanner``'s resolved image for an ``ImageResource``,
    without ever touching the base class's own (CWD-dependent, unscaled) resolution.

    **Test steps:**

    * attach a scanner mocked to resolve any name to a real ``QImage``
    * resolve an image resource
    * verify the scanner's image comes back and the base ``loadResource`` was never called
    """
    scanner_image = QImage(100, 50, QImage.Format.Format_RGB32)
    scanner = mocker.Mock(get_markdown_viewer_image=mocker.Mock(return_value=scanner_image))
    base_load = mocker.patch.object(QTextBrowser, "loadResource")
    view = MarkdownView(image_scanner=scanner)
    qtbot.addWidget(view)

    loaded = view.loadResource(int(QTextDocument.ResourceType.ImageResource), QUrl("cover.jpg"))

    assert loaded is scanner_image
    scanner.get_markdown_viewer_image.assert_called_once_with("cover.jpg", view.devicePixelRatio())
    base_load.assert_not_called()


def test_load_resource_falls_back_when_the_scanner_cannot_resolve_the_name(qtbot: QtBot, mocker: MockerFixture) -> None:
    """`loadResource` falls back to the base class when the scanner returns ``None``.

    **Test steps:**

    * attach a scanner mocked to fail to resolve a name
    * resolve an image resource
    * verify the base class's own return value comes back
    """
    scanner = mocker.Mock(get_markdown_viewer_image=mocker.Mock(return_value=None))
    base_load = mocker.patch.object(QTextBrowser, "loadResource", return_value="base-fallback")
    view = MarkdownView(image_scanner=scanner)
    qtbot.addWidget(view)

    loaded = view.loadResource(int(QTextDocument.ResourceType.ImageResource), QUrl("missing.jpg"))

    assert loaded == "base-fallback"
    base_load.assert_called_once()


def test_load_resource_ignores_the_scanner_for_a_non_image_resource(qtbot: QtBot, mocker: MockerFixture) -> None:
    """`loadResource` never consults the scanner for a non-``ImageResource`` type.

    **Test steps:**

    * attach a scanner
    * resolve a ``StyleSheetResource``
    * verify the scanner was never called and the base class's return value comes back
    """
    scanner = mocker.Mock(get_markdown_viewer_image=mocker.Mock(return_value=None))
    mocker.patch.object(QTextBrowser, "loadResource", return_value="base-fallback")
    view = MarkdownView(image_scanner=scanner)
    qtbot.addWidget(view)

    loaded = view.loadResource(int(QTextDocument.ResourceType.StyleSheetResource), QUrl("style.css"))

    assert loaded == "base-fallback"
    scanner.get_markdown_viewer_image.assert_not_called()


def test_load_resource_without_a_scanner_always_falls_back(qtbot: QtBot, mocker: MockerFixture) -> None:
    """`loadResource` always uses the base class's own resolution when no scanner is attached.

    **Test steps:**

    * build a viewer with no ``image_scanner``
    * resolve an image resource
    * verify the base class's return value comes back unchanged
    """
    mocker.patch.object(QTextBrowser, "loadResource", return_value="base-fallback")
    view = MarkdownView()
    qtbot.addWidget(view)

    loaded = view.loadResource(int(QTextDocument.ResourceType.ImageResource), QUrl("cover.jpg"))

    assert loaded == "base-fallback"
