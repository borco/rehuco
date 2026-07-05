"""Tests for the mkdocs hook that styles `[[doc#slug]]` / `[[[doc#slug]]]` tokens as `.slug-ref` spans."""

from typing import Any

import markdown

from tools.mkdocs_slug_ref_hook import SlugRefExtension, on_config

# region Fixtures / helpers


def render(text: str) -> str:
    """Render ``text`` through Markdown with only :class:`SlugRefExtension` enabled.

    :param text: the markdown source to render.
    :returns: the rendered HTML body.
    """
    return markdown.markdown(text, extensions=[SlugRefExtension()])


# endregion

# region SlugRefExtension tests


def test_reference_token_is_wrapped_in_slug_ref_span() -> None:
    """A double-bracket reference renders as a `.slug-ref` span, brackets included.

    **Test steps:**

    * render a sentence containing `[[plugins#field-toolkit]]`
    * verify the output wraps the exact token text in `<span class="slug-ref">`
    """
    html = render("See [[plugins#field-toolkit]] for details.")

    assert '<span class="slug-ref">[[plugins#field-toolkit]]</span>' in html


def test_declaration_token_is_wrapped_in_slug_ref_span() -> None:
    """A triple-bracket declaration renders the same way as a reference, extra bracket included.

    **Test steps:**

    * render a standalone triple-bracket declaration line
    * verify the output wraps the exact token text (all three brackets) in `<span class="slug-ref">`
    """
    html = render("[[[plugins#field-toolkit]]]")

    assert '<span class="slug-ref">[[[plugins#field-toolkit]]]</span>' in html


def test_whole_document_reference_is_wrapped() -> None:
    """A slug-less whole-document reference (`[[doc]]`) is matched too.

    **Test steps:**

    * render a sentence containing bare `[[data-model]]`
    * verify it is wrapped in `<span class="slug-ref">`
    """
    html = render("See [[data-model]] for the schema.")

    assert '<span class="slug-ref">[[data-model]]</span>' in html


def test_whole_document_declaration_is_wrapped() -> None:
    """A slug-less whole-document declaration (`[[[doc]]]`) is matched too.

    **Test steps:**

    * render a standalone `[[[data-model]]]` declaration line
    * verify it is wrapped in `<span class="slug-ref">`
    """
    html = render("[[[data-model]]]")

    assert '<span class="slug-ref">[[[data-model]]]</span>' in html


def test_token_inside_backticks_is_left_as_plain_code() -> None:
    """A token shown as a literal example inside backticks is not re-wrapped.

    **Test steps:**

    * render a sentence showing `` `[[[doc#slug]]]` `` as a literal example
    * verify the output contains a plain `<code>` element with no nested `.slug-ref` span
    """
    html = render("Written as `[[[doc#slug]]]` in prose.")

    assert "<code>[[[doc#slug]]]</code>" in html
    assert "slug-ref" not in html


def test_token_inside_fenced_code_block_is_left_untouched() -> None:
    """A token inside a fenced code block is never reached by inline processing.

    **Test steps:**

    * render a fenced code block containing a declaration-shaped line
    * verify the output has no `.slug-ref` span
    """
    html = render("```\n[[[plugins#field-toolkit]]]\n```")

    assert "slug-ref" not in html


# endregion

# region on_config tests


def test_on_config_appends_slug_ref_extension() -> None:
    """`on_config` appends a `SlugRefExtension` instance to the config's markdown extensions.

    **Test steps:**

    * call `on_config` with a config exposing an empty `markdown_extensions` list
    * verify exactly one `SlugRefExtension` instance was appended
    * verify the same config object is returned
    """
    config: dict[str, Any] = {"markdown_extensions": []}

    result = on_config(config)

    assert result is config
    assert len(config["markdown_extensions"]) == 1
    assert isinstance(config["markdown_extensions"][0], SlugRefExtension)


# endregion
