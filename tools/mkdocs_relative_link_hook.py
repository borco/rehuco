"""mkdocs hook: rewrite relative links whose target falls outside `docs_dir` (e.g. a link from a
spec into `apps/`, `packages/`, or `spikes/`) to an absolute `{repo_url}/blob-or-tree/{branch}/...`
link, at build time only (see `docs/specs/appendices/code-conventions.md`'s Markdown section).

GitHub uses `/blob/` for a file and `/tree/` for a directory -- `/blob/` on a directory happens to
302-redirect to the `/tree/` equivalent today, but that's undocumented redirect behavior, not a
contract, so this checks the real, on-disk target (this hook only ever runs against a real repo
checkout) rather than relying on it.

GitHub already resolves such a relative link natively (repo-tree-relative resolution) when the doc
is viewed as a blob or in a PR -- nothing to change there. The published mkdocs site only ever
publishes `docs_dir`, so the same link 404s once built. Doc source stays plain relative links
everywhere; this hook is the one build-time adjustment needed, and only touches links this actually
applies to -- one already inside `docs_dir`, or an absolute/external one, passes through untouched.

Registered via `mkdocs.yml`'s `hooks:` list, not `markdown_extensions:`, for the same `tools/`-is-
not-an-installed-package reason documented in `mkdocs_slug_ref_hook.py`. Rewriting happens in a
`Treeprocessor` (walks the already-parsed `<a>` elements) rather than a regex over raw markdown, so
a link shown as a literal code example in prose is never mistaken for a real one -- it was never
parsed into an `<a>` element to begin with.
"""

import os
import posixpath
from typing import Any, Final
from urllib.parse import urlsplit

from markdown import Extension
from markdown.core import Markdown
from markdown.treeprocessors import Treeprocessor
from mkdocs.structure.pages import Page

# Below 'prettify' (10) and 'inline' (20): both must have already turned markdown link syntax into
# real `<a>` elements before this walks the tree looking for them.
PRIORITY: Final = 4


class RelativeLinkTreeprocessor(Treeprocessor):  # pylint: disable=too-few-public-methods
    """Rewrites every `<a href>` in the tree whose target resolves outside `docs_dir`."""

    def __init__(self, md: Markdown, extension: RelativeLinkExtension) -> None:
        """Store the shared, page-context-carrying extension instance.

        :param md: the Markdown instance being configured.
        :param extension: the extension holding repo/branch config and the current page's directory.
        """
        super().__init__(md)
        self._extension = extension

    def run(self, root: Any) -> Any:
        """Rewrite out-of-`docs_dir` hrefs in place.

        :param root: the document's root element.
        :returns: the same root, with qualifying `href` attributes rewritten.
        """
        for anchor in root.iter("a"):
            href = anchor.get("href")
            if not href:
                continue
            rewritten = self._extension.rewrite_href(href)
            if rewritten is not None:
                anchor.set("href", rewritten)
        return root


class RelativeLinkExtension(Extension):
    """Holds the repo/branch config and the current page's directory, for the treeprocessor."""

    def __init__(self, repo_url: str, branch: str, repo_root: str, docs_dir_name: str) -> None:
        """Store this build's repo/branch/docs-dir config.

        :param repo_url: the repo's web URL, e.g. ``https://github.com/borco/rehuco``.
        :param branch: the branch links should point at, e.g. ``master``.
        :param repo_root: the repo's absolute filesystem root, to tell a directory target from a
            file one.
        :param docs_dir_name: `docs_dir`'s path relative to the repo root, posix-separated.
        """
        super().__init__()
        self.repo_url = repo_url.rstrip("/")
        self.branch = branch
        self.repo_root = repo_root
        self.docs_dir_name = docs_dir_name
        self.page_dir = ""

    def extendMarkdown(self, md: Markdown) -> None:
        """Register :class:`RelativeLinkTreeprocessor` below the built-in `inline`/`prettify` steps.

        :param md: the Markdown instance being configured.
        """
        md.treeprocessors.register(RelativeLinkTreeprocessor(md, self), "relative_link", PRIORITY)

    def rewrite_href(self, href: str) -> str | None:
        """Rewrite ``href`` to a repo blob/tree URL if it targets something outside `docs_dir`.

        :param href: the link target exactly as written in the source markdown.
        :returns: the replacement URL, or ``None`` if ``href`` needs no change (already absolute,
            external, an in-page anchor, or already inside `docs_dir`).
        """
        scheme, netloc, path, _query, fragment = urlsplit(href)
        if scheme or netloc or not path:
            return None
        target_rel_to_docs = posixpath.normpath(posixpath.join(self.page_dir, path))
        if target_rel_to_docs != ".." and not target_rel_to_docs.startswith("../"):
            return None
        repo_rel_path = posixpath.normpath(f"{self.docs_dir_name}/{target_rel_to_docs}")
        abs_target = os.path.join(self.repo_root, *repo_rel_path.split("/"))
        segment = "tree" if os.path.isdir(abs_target) else "blob"
        url = f"{self.repo_url}/{segment}/{self.branch}/{repo_rel_path}"
        return f"{url}#{fragment}" if fragment else url


def branch_from_edit_uri(edit_uri: str) -> str:
    """Extract the branch name mkdocs is already configured with, from `edit_uri`.

    :param edit_uri: the configured `edit_uri`, e.g. ``"edit/master/docs/"``.
    :returns: the branch segment, e.g. ``"master"`` -- kept in one place (`edit_uri`) rather than
        adding a second hardcoded branch name here.
    """
    return edit_uri.split("/")[1]


def on_config(config: dict[str, Any]) -> dict[str, Any]:
    """mkdocs hook entry point: append a configured :class:`RelativeLinkExtension` to the build.

    :param config: the mkdocs build configuration.
    :returns: the same configuration, with the extension appended.
    """
    repo_root = os.path.dirname(config["config_file_path"])
    docs_dir_name = os.path.relpath(config["docs_dir"], repo_root).replace(os.sep, "/")
    extension = RelativeLinkExtension(
        repo_url=config["repo_url"],
        branch=branch_from_edit_uri(config["edit_uri"]),
        repo_root=repo_root,
        docs_dir_name=docs_dir_name,
    )
    config["markdown_extensions"].append(extension)
    return config


def on_page_markdown(
    markdown: str,
    page: Page,
    config: dict[str, Any],
    files: Any,  # pylint: disable=unused-argument
) -> str:
    """mkdocs hook entry point: stash the page about to be rendered, for `rewrite_href` to resolve
    its relative links against.

    :param markdown: the page's raw markdown source, returned unchanged.
    :param page: the page about to be rendered.
    :param config: the mkdocs build configuration; carries the :class:`RelativeLinkExtension`
        `on_config` appended, which this looks back up rather than duplicating in a module global.
    :param files: the full build file collection (unused; required by the `on_page_markdown` hook
        signature regardless).
    :returns: ``markdown``, unchanged -- this hook only records page context as a side effect.
    """
    extension = next(ext for ext in config["markdown_extensions"] if isinstance(ext, RelativeLinkExtension))
    extension.page_dir = posixpath.dirname(page.file.src_uri)
    return markdown
