"""Tests for the mkdocs hook that rewrites relative links resolving outside `docs_dir` to
absolute GitHub blob/tree URLs."""

import os
from types import SimpleNamespace
from typing import Any, cast

import markdown
from mkdocs.structure.pages import Page
from pytest_mock import MockerFixture

from tools.mkdocs_relative_link_hook import (
    RelativeLinkExtension,
    branch_from_edit_uri,
    on_config,
    on_page_markdown,
)

REPO_URL = "https://github.com/borco/rehuco"
BRANCH = "master"
REPO_ROOT = "/repo"
DOCS_DIR_NAME = "docs"

# region Fixtures / helpers


def make_extension(page_dir: str = "") -> RelativeLinkExtension:
    """Build a :class:`RelativeLinkExtension` configured like a real build, for one page.

    :param page_dir: the rendering page's directory, relative to `docs_dir`.
    :returns: the configured extension, ready to register with `markdown.markdown`.
    """
    extension = RelativeLinkExtension(
        repo_url=REPO_URL, branch=BRANCH, repo_root=REPO_ROOT, docs_dir_name=DOCS_DIR_NAME
    )
    extension.page_dir = page_dir
    return extension


def render(text: str, page_dir: str = "") -> str:
    """Render ``text`` through Markdown with only :class:`RelativeLinkExtension` enabled.

    :param text: the markdown source to render.
    :param page_dir: the rendering page's directory, relative to `docs_dir`.
    :returns: the rendered HTML body.
    """
    return markdown.markdown(text, extensions=[make_extension(page_dir)])


def make_config() -> dict[str, Any]:
    """Build a fake mkdocs config with just the keys `on_config` reads.

    :returns: a config dict with an empty `markdown_extensions` list, a repo root at `/repo`, and
        `docs_dir` at its `docs` subdirectory -- `docs_dir_name` derivation is pure string
        manipulation, so no real filesystem paths are needed.
    """
    return {
        "markdown_extensions": [],
        "config_file_path": "/repo/mkdocs.yml",
        "docs_dir": "/repo/docs",
        "repo_url": REPO_URL,
        "edit_uri": "edit/master/docs/",
    }


# endregion

# region RelativeLinkExtension.rewrite_href tests


def test_link_inside_docs_dir_is_left_untouched() -> None:
    """A relative link resolving to a file still inside `docs_dir` is not rewritten.

    **Test steps:**

    * render a link to a sibling spec file from a page at the docs root
    * verify the href is unchanged
    """
    html = render("[data model](specs/data-model.md)")

    assert '<a href="specs/data-model.md">' in html


def test_link_outside_docs_dir_is_rewritten_to_blob_url() -> None:
    """A relative link resolving outside `docs_dir` is rewritten to a GitHub blob URL.

    **Test steps:**

    * render a link from a nested spec page to a source file under `packages/`
    * verify the href becomes `{repo_url}/blob/{branch}/packages/...`
    """
    html = render("[toolkit](../../../packages/rehuco-agent/toolkit.py)", page_dir="specs/appendices")

    assert f'<a href="{REPO_URL}/blob/{BRANCH}/packages/rehuco-agent/toolkit.py">' in html


def test_link_to_directory_outside_docs_dir_is_rewritten_to_tree_url(mocker: MockerFixture) -> None:
    """A relative link resolving to a *directory* outside `docs_dir` uses `/tree/`, not `/blob/` --
    GitHub's own distinction, checked against the real on-disk target rather than assumed.

    **Test steps:**

    * mock the on-disk check so the resolved target reports as a directory
    * render a link from a nested spec page to a directory under `packages/`
    * verify the href becomes `{repo_url}/tree/{branch}/packages/...`
    """
    mocker.patch.object(os.path, "isdir", return_value=True)

    html = render("[agent app](../../../packages/rehuco-agent)", page_dir="specs/appendices")

    assert f'<a href="{REPO_URL}/tree/{BRANCH}/packages/rehuco-agent">' in html


def test_fragment_is_preserved_on_rewritten_link() -> None:
    """A `#Lnn`-style fragment survives the rewrite, since GitHub's blob view understands it.

    **Test steps:**

    * render an outside-`docs_dir` link carrying a line-anchor fragment
    * verify the fragment is appended to the rewritten blob URL
    """
    html = render("[toolkit](../../../packages/rehuco-agent/toolkit.py#L42)", page_dir="specs/appendices")

    assert f'<a href="{REPO_URL}/blob/{BRANCH}/packages/rehuco-agent/toolkit.py#L42">' in html


def test_absolute_external_link_is_left_untouched() -> None:
    """A link to an external site is never touched.

    **Test steps:**

    * render a link to an external URL
    * verify the href is unchanged
    """
    html = render("[mkdocs](https://www.mkdocs.org/)")

    assert '<a href="https://www.mkdocs.org/">' in html


def test_anchor_only_link_is_left_untouched() -> None:
    """A same-page `#anchor` link (empty path) is never touched.

    **Test steps:**

    * render a same-page anchor link
    * verify the href is unchanged
    """
    html = render("[see above](#some-heading)")

    assert '<a href="#some-heading">' in html


def test_anchor_with_no_href_is_skipped() -> None:
    """An `<a>` element with no (or an empty) `href` is left alone, not treated as a rewrite target.

    **Test steps:**

    * render an empty-target link, producing an `<a>` with `href=""`
    * verify it comes through unrewritten
    """
    html = render("[empty]()")

    assert '<a href="">empty</a>' in html


def test_link_inside_fenced_code_block_is_never_reached() -> None:
    """A link shown as a literal example inside a fenced code block is never touched, since the
    tree-based rewrite only ever sees real `<a>` elements, and code-block text is never parsed
    into one.

    **Test steps:**

    * render a fenced code block containing markdown link syntax pointing outside `docs_dir`
    * verify no `<a href` element appears in the output
    """
    html = render("```\n[toolkit](../../packages/rehuco-agent/toolkit.py)\n```", page_dir="specs/appendices")

    assert "<a href" not in html


# endregion

# region branch_from_edit_uri tests


def test_branch_from_edit_uri_extracts_the_middle_segment() -> None:
    """`branch_from_edit_uri` pulls the branch out of a standard `edit/<branch>/docs/` value.

    **Test steps:**

    * call it with `"edit/master/docs/"`
    * verify it returns `"master"`
    """
    assert branch_from_edit_uri("edit/master/docs/") == "master"


# endregion

# region on_config / on_page_markdown tests


def test_on_config_appends_extension_and_derives_docs_dir_name() -> None:
    """`on_config` appends a configured `RelativeLinkExtension`, deriving `docs_dir_name` purely
    from `config_file_path`/`docs_dir` (no filesystem access).

    **Test steps:**

    * call `on_config` with a fake config pointing `config_file_path` at a repo root and `docs_dir`
      at that root's `docs` subdirectory
    * verify exactly one `RelativeLinkExtension` was appended, configured with `docs_dir_name="docs"`,
      `repo_root` matching `config_file_path`'s directory, and the branch parsed out of `edit_uri`
    * verify the same config object is returned
    """
    config = make_config()

    result = on_config(config)

    assert result is config
    assert len(config["markdown_extensions"]) == 1
    extension = config["markdown_extensions"][0]
    assert isinstance(extension, RelativeLinkExtension)
    assert extension.docs_dir_name == "docs"
    assert extension.repo_root == "/repo"
    assert extension.branch == "master"


def test_on_page_markdown_sets_page_dir_from_page_file_src_uri() -> None:
    """`on_page_markdown` derives `page_dir` from the rendering page's `file.src_uri`, leaving the
    markdown source itself unchanged.

    **Test steps:**

    * run `on_config` to install a `RelativeLinkExtension`
    * call `on_page_markdown` with a stub page whose `file.src_uri` is a nested spec path
    * verify the extension's `page_dir` becomes that path's directory
    * verify the markdown source is returned unchanged
    """
    config = make_config()
    on_config(config)
    extension = config["markdown_extensions"][0]
    page = cast(Page, SimpleNamespace(file=SimpleNamespace(src_uri="specs/appendices/code-conventions.md")))

    result = on_page_markdown("some markdown", page, config, files=None)

    assert result == "some markdown"
    assert extension.page_dir == "specs/appendices"


# endregion
