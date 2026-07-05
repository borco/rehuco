"""mkdocs hook: style `[[doc#slug]]` / `[[[doc#slug]]]` cross-reference tokens (see
`docs/specs/README.md`'s "Symbolic cross-references" section) as inline-code-*like* spans on the
published site, without making them `<code>` elements or clickable links -- that section explicitly
rejects link parity for this token.

Registered via `mkdocs.yml`'s `hooks:` list (a file path, not a dotted import) rather than
`markdown_extensions:` (a dotted import resolved through the `markdown` library's ambient
`sys.path`) because `tools/` is a plain source directory, not an installed package -- there is no
guarantee the repo root is on `sys.path` when `uv run mkdocs ...` starts. `on_config` sidesteps this
by appending an already-instantiated `SlugRefExtension` object directly to
`config["markdown_extensions"]`; `markdown.Markdown(extensions=...)` is built fresh per page,
*after* `on_config` hooks run, and accepts extension instances alongside name strings, so this needs
no import path at all. Do not "simplify" this back into a `markdown_extensions:` string entry --
that reintroduces the sys.path dependency this design avoids.
"""

import re
import xml.etree.ElementTree as etree
from typing import Any

from markdown import Extension
from markdown.core import Markdown
from markdown.inlinepatterns import InlineProcessor

SLUG_REF_PATTERN = r"\[\[\[?[a-zA-Z0-9_.-]+(?:#[a-zA-Z0-9-]+)?\]\]\]?"

# Below the built-in `backtick` pattern's priority (190): a token already shown as a literal
# example inside backticks is stashed as an unmatchable AtomicString by `backtick` first, so it
# never reaches this pattern -- mirrors, without duplicating, check_slug_refs.py's own
# inline-code-stripping logic.
_PRIORITY = 175


class SlugRefInlineProcessor(InlineProcessor):
    """Wraps a matched cross-reference token in a `.slug-ref`-styled `<span>`, brackets included."""

    def handleMatch(self, m: re.Match[str], data: str) -> tuple[etree.Element, int, int]:
        """Build the replacement `<span>` for one regex match.

        :param m: the regex match against ``data``.
        :param data: the full inline text being scanned (unused; the match is self-contained).
        :returns: the replacement element and the ``(start, end)`` span it replaces.
        """
        el = etree.Element("span")
        el.set("class", "slug-ref")
        el.text = m.group(0)
        return el, m.start(0), m.end(0)


class SlugRefExtension(Extension):
    """Registers :class:`SlugRefInlineProcessor` with the Markdown parser."""

    def extendMarkdown(self, md: Markdown) -> None:
        """Register the inline processor below the built-in `backtick` pattern's priority.

        :param md: the Markdown instance being configured.
        """
        md.inlinePatterns.register(SlugRefInlineProcessor(SLUG_REF_PATTERN), "slug_ref", _PRIORITY)


def on_config(config: dict[str, Any]) -> dict[str, Any]:
    """mkdocs hook entry point: append :class:`SlugRefExtension` to the build's markdown extensions.

    :param config: the mkdocs build configuration.
    :returns: the same configuration, with the extension appended.
    """
    config["markdown_extensions"].append(SlugRefExtension())
    return config
