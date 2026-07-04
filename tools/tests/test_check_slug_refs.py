"""Tests for the `[[doc#slug]]` / `[[[doc#slug]]]` cross-reference validator."""

from pathlib import Path

from pytest_mock import MockerFixture

from tools import check_slug_refs

# region Fixtures / helpers


def run_main(mocker: MockerFixture, files: dict[Path, list[str]]) -> tuple[int, str]:
    """Run ``main()`` against fake in-memory source files, with no real disk I/O.

    :param mocker: pytest-mock fixture.
    :param files: mapping of fake ``Path`` -> its lines, standing in for the repo's source tree.
    :returns: the process exit code and everything printed to stdout.
    """
    mocker.patch.object(check_slug_refs, "iter_source_files", return_value=list(files))
    mocker.patch.object(Path, "read_text", lambda self, encoding="utf-8": "\n".join(files[self]) + "\n")
    print_mock = mocker.patch("builtins.print")

    exit_code = check_slug_refs.main()

    output = "\n".join(call.args[0] for call in print_mock.call_args_list)
    return exit_code, output


# endregion

# region strip_markdown_code tests


def test_strip_markdown_code_blanks_inline_code_spans() -> None:
    """Inline code spans are blanked so a literal example token isn't mistaken for a real one.

    **Test steps:**

    * pass a line containing a `[[[doc#slug]]]` example wrapped in backticks
    * verify the backtick-quoted content is removed from the returned line
    """
    lines = ["See `` `[[[doc#slug]]]` `` for the format."]

    result = check_slug_refs.strip_markdown_code(lines)

    assert "[[[doc#slug]]]" not in result[0]


def test_strip_markdown_code_blanks_fenced_blocks() -> None:
    """Content inside a fenced code block is blanked entirely, fence markers included.

    **Test steps:**

    * pass a fenced block containing a `[[doc#slug]]`-shaped line
    * verify every line inside (and the fences themselves) comes back blank
    """
    lines = ["```markdown", "[[[plugins#field-toolkit]]]", "```"]

    result = check_slug_refs.strip_markdown_code(lines)

    assert result == ["", "", ""]


def test_strip_markdown_code_leaves_plain_prose_untouched() -> None:
    """A normal prose line with no code markup passes through unchanged.

    **Test steps:**

    * pass a plain sentence referencing a slug outside any code span
    * verify it comes back exactly as given
    """
    lines = ["See [[plugins#field-toolkit]] for details."]

    result = check_slug_refs.strip_markdown_code(lines)

    assert result == lines


# endregion

# region expected_doc_key tests


def test_expected_doc_key_for_top_level_spec() -> None:
    """A top-level spec file's doc-key is its bare filename stem.

    **Test steps:**

    * build a path under `docs/specs/plugins.md`
    * verify the expected doc-key is ``"plugins"``
    """
    path = check_slug_refs.SPECS_ROOT / "plugins.md"

    assert check_slug_refs.expected_doc_key(path) == "plugins"


def test_expected_doc_key_for_appendix() -> None:
    """An appendix file's doc-key is dot-qualified with ``appendices.``.

    **Test steps:**

    * build a path under `docs/specs/appendices/testing.md`
    * verify the expected doc-key is ``"appendices.testing"``
    """
    path = check_slug_refs.SPECS_ROOT / "appendices" / "testing.md"

    assert check_slug_refs.expected_doc_key(path) == "appendices.testing"


def test_expected_doc_key_none_outside_specs() -> None:
    """A file outside `docs/specs/` has no expected doc-key -- declarations don't belong there.

    **Test steps:**

    * build a path under `apps/rehuco-agent/src/rehuco_agent/app.py`
    * verify the expected doc-key is ``None``
    """
    path = check_slug_refs.REPO_ROOT / "apps" / "rehuco-agent" / "src" / "rehuco_agent" / "app.py"

    assert check_slug_refs.expected_doc_key(path) is None


# endregion

# region main() integration tests


def test_main_passes_with_matching_declaration_and_reference(mocker: MockerFixture) -> None:
    """A declaration with one resolving reference is a clean pass.

    **Test steps:**

    * declare `[[[plugins#overview]]]` in `plugins.md` and reference `[[plugins#overview]]` in
      another file
    * verify `main()` returns 0
    """
    plugins_md = check_slug_refs.SPECS_ROOT / "plugins.md"
    other_md = check_slug_refs.SPECS_ROOT / "data-model.md"
    files = {
        plugins_md: ["# §13. Plugins", "", "[[[plugins#overview]]]", "", "Some prose."],
        other_md: ["# §4. Data Model", "", "See [[plugins#overview]] for the split."],
    }

    exit_code, output = run_main(mocker, files)

    assert exit_code == 0
    assert "1 declarations, 1 references, all resolve" in output


def test_main_fails_on_duplicate_declaration(mocker: MockerFixture) -> None:
    """The same `(doc, slug)` declared twice is reported as a duplicate.

    **Test steps:**

    * declare `[[[plugins#overview]]]` in two different files
    * verify `main()` returns 1 and reports both sites
    """
    plugins_md = check_slug_refs.SPECS_ROOT / "plugins.md"
    other_md = check_slug_refs.SPECS_ROOT / "data-model.md"
    files = {
        plugins_md: ["[[[plugins#overview]]]"],
        other_md: ["[[[plugins#overview]]]"],
    }

    exit_code, output = run_main(mocker, files)

    assert exit_code == 1
    assert "duplicate declaration [[plugins#overview]]" in output


def test_main_fails_on_unresolved_reference(mocker: MockerFixture) -> None:
    """A reference with no matching declaration anywhere is reported as unresolved.

    **Test steps:**

    * reference `[[plugins#missing]]` with no declaration anywhere in the fake tree
    * verify `main()` returns 1 and names the missing token
    """
    other_md = check_slug_refs.SPECS_ROOT / "data-model.md"
    files = {other_md: ["See [[plugins#missing]] for details."]}

    exit_code, output = run_main(mocker, files)

    assert exit_code == 1
    assert "[[plugins#missing]] has no declaration" in output


def test_main_fails_on_doc_key_mismatch(mocker: MockerFixture) -> None:
    """A declaration whose doc-key doesn't match its own file's path is flagged.

    **Test steps:**

    * declare `[[[typo#overview]]]` inside `plugins.md` (should be `plugins`, not `typo`)
    * verify `main()` returns 1 and names the expected doc-key
    """
    plugins_md = check_slug_refs.SPECS_ROOT / "plugins.md"
    files = {plugins_md: ["[[[typo#overview]]]"]}

    exit_code, output = run_main(mocker, files)

    assert exit_code == 1
    assert "should use doc-key 'plugins'" in output


def test_main_ignores_tokens_inside_code_spans(mocker: MockerFixture) -> None:
    """A token shown only as a literal code-quoted example is never treated as a reference.

    **Test steps:**

    * put `` `[[plugins#overview]]` `` (backtick-quoted) in a file, with no real declaration
    * verify `main()` still passes, since the quoted token is stripped before scanning
    """
    other_md = check_slug_refs.SPECS_ROOT / "data-model.md"
    files = {other_md: ["Example syntax: `[[plugins#overview]]`."]}

    exit_code, output = run_main(mocker, files)

    assert exit_code == 0
    assert "0 declarations, 0 references" in output


def test_main_does_not_confuse_reference_inside_a_declaration_line(mocker: MockerFixture) -> None:
    """A triple-bracket declaration line isn't also double-counted as a double-bracket reference.

    **Test steps:**

    * declare `[[[plugins#overview]]]` alone on its line, nothing else in the tree
    * verify exactly one declaration and zero references are found
    """
    plugins_md = check_slug_refs.SPECS_ROOT / "plugins.md"
    files = {plugins_md: ["[[[plugins#overview]]]"]}

    exit_code, output = run_main(mocker, files)

    assert exit_code == 0
    assert "1 declarations, 0 references, all resolve" in output


# endregion
