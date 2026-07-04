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


def test_expected_doc_key_lowercases_an_uppercase_stem() -> None:
    """A file whose stem isn't already lowercase (e.g. `README.md`) still gets a lowercase doc-key.

    **Test steps:**

    * build a path under `docs/specs/README.md`
    * verify the expected doc-key is ``"readme"``, not ``"README"``
    """
    path = check_slug_refs.SPECS_ROOT / "README.md"

    assert check_slug_refs.expected_doc_key(path) == "readme"


def test_expected_doc_key_none_outside_specs() -> None:
    """A file outside `docs/specs/` has no expected doc-key -- declarations don't belong there.

    **Test steps:**

    * build a path under `apps/rehuco-agent/src/rehuco_agent/app.py`
    * verify the expected doc-key is ``None``
    """
    path = check_slug_refs.REPO_ROOT / "apps" / "rehuco-agent" / "src" / "rehuco_agent" / "app.py"

    assert check_slug_refs.expected_doc_key(path) is None


# endregion

# region iter_repo_files tests


def test_iter_repo_files_parses_git_ls_files_output(mocker: MockerFixture) -> None:
    """`git ls-files -z` output is split on NUL and resolved to absolute repo-root paths.

    **Test steps:**

    * fake `subprocess.run` to return a NUL-separated `stdout` with a trailing separator
    * verify each non-empty entry becomes an absolute path under `REPO_ROOT`
    """
    fake_stdout = "CLAUDE.md\0docs/specs/plugins.md\0"
    mocker.patch.object(check_slug_refs.subprocess, "run", return_value=mocker.Mock(stdout=fake_stdout))

    result = check_slug_refs.iter_repo_files()

    assert result == [
        check_slug_refs.REPO_ROOT / "CLAUDE.md",
        check_slug_refs.REPO_ROOT / "docs" / "specs" / "plugins.md",
    ]


# endregion

# region iter_source_files tests


def test_iter_source_files_includes_markdown_and_python_files(mocker: MockerFixture) -> None:
    """Every tracked `.md` under `docs/` and `.py` under `apps/`/`packages/` is included.

    **Test steps:**

    * fake `iter_repo_files()` to return one file each for `docs/`, `apps/`, and `packages/`
    * verify all three come back from `iter_source_files()`
    """
    docs_md = check_slug_refs.REPO_ROOT / "docs" / "specs" / "plugins.md"
    apps_py = check_slug_refs.REPO_ROOT / "apps" / "rehuco-agent" / "app.py"
    packages_py = check_slug_refs.REPO_ROOT / "packages" / "rehuco-core" / "core.py"
    mocker.patch.object(check_slug_refs, "iter_repo_files", return_value=[docs_md, apps_py, packages_py])

    assert check_slug_refs.iter_source_files() == [docs_md, apps_py, packages_py]


def test_iter_source_files_excludes_generated_ui_and_rc_files(mocker: MockerFixture) -> None:
    """Generated `_ui.py` / `_rc.py` files are skipped -- gitignored, never hand-edited.

    **Test steps:**

    * fake `iter_repo_files()` under `apps/` to return a real `.py`, a `_ui.py`, and a `_rc.py`
    * verify only the real `.py` file survives
    """
    real_py = check_slug_refs.REPO_ROOT / "apps" / "rehuco-agent" / "app.py"
    generated_ui = check_slug_refs.REPO_ROOT / "apps" / "rehuco-agent" / "main_window_ui.py"
    generated_rc = check_slug_refs.REPO_ROOT / "apps" / "rehuco-agent" / "resources_rc.py"
    mocker.patch.object(check_slug_refs, "iter_repo_files", return_value=[real_py, generated_ui, generated_rc])

    assert check_slug_refs.iter_source_files() == [real_py]


def test_iter_source_files_includes_root_claude_md(mocker: MockerFixture) -> None:
    """The root `CLAUDE.md` is scanned even though it lives outside `docs/`.

    **Test steps:**

    * fake `iter_repo_files()` to return only `CLAUDE.md` at the repo root
    * verify it comes back from `iter_source_files()`
    """
    claude_md = check_slug_refs.REPO_ROOT / "CLAUDE.md"
    mocker.patch.object(check_slug_refs, "iter_repo_files", return_value=[claude_md])

    assert check_slug_refs.iter_source_files() == [claude_md]


def test_iter_source_files_includes_readme_anywhere(mocker: MockerFixture) -> None:
    """Any tracked `README.md`, anywhere in the tree, is scanned.

    **Test steps:**

    * fake `iter_repo_files()` to return a `README.md` nested several directories deep
    * verify it comes back from `iter_source_files()`
    """
    nested_readme = check_slug_refs.REPO_ROOT / "apps" / "rehuco-agent" / "launcher" / "README.md"
    mocker.patch.object(check_slug_refs, "iter_repo_files", return_value=[nested_readme])

    assert check_slug_refs.iter_source_files() == [nested_readme]


def test_iter_source_files_excludes_unrelated_top_level_markdown(mocker: MockerFixture) -> None:
    """A `.md` file that is neither under `docs/` nor named `CLAUDE.md`/`README.md` is skipped.

    **Test steps:**

    * fake `iter_repo_files()` to return a hypothetical `CHANGELOG.md` at the repo root
    * verify it does not come back from `iter_source_files()`
    """
    changelog_md = check_slug_refs.REPO_ROOT / "CHANGELOG.md"
    mocker.patch.object(check_slug_refs, "iter_repo_files", return_value=[changelog_md])

    assert not check_slug_refs.iter_source_files()


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
    assert "duplicate declaration [[[plugins#overview]]]" in output


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


def test_main_fails_on_uppercase_doc_key(mocker: MockerFixture) -> None:
    """A declaration using the file's uppercase stem instead of its lowercased doc-key is flagged.

    **Test steps:**

    * declare `[[[README]]]` inside `README.md` (should be `readme`, not `README`)
    * verify `main()` returns 1 and names the expected lowercase doc-key
    """
    readme_md = check_slug_refs.SPECS_ROOT / "README.md"
    files = {readme_md: ["[[[README]]]"]}

    exit_code, output = run_main(mocker, files)

    assert exit_code == 1
    assert "should use doc-key 'readme'" in output


def test_main_fails_when_case_variant_filenames_collide(mocker: MockerFixture) -> None:
    """`README.md` and `readme.md` would normalize to the same doc-key and collide as a duplicate.

    Demonstrates why the two must never coexist: lowercasing the doc-key means a same-named file
    differing only in case is indistinguishable from the original, so each declaring its own
    whole-document anchor collides as the same `(doc, slug)` pair. (A plain `dict[Path, ...]` can't
    even hold both as distinct keys on a case-insensitive filesystem -- `Path("README.md") ==
    Path("readme.md")` is `True` on Windows -- so this test keys fake file content by `str(path)`
    instead of relying on `run_main`'s dict-keyed-by-`Path` fixture.)

    **Test steps:**

    * declare `[[[readme]]]` in both a `README.md` path and a `readme.md` path
    * verify `main()` returns 1 and reports a duplicate declaration
    """
    upper_md = check_slug_refs.SPECS_ROOT / "README.md"
    lower_md = check_slug_refs.SPECS_ROOT / "readme.md"
    content_by_str = {str(upper_md): ["[[[readme]]]"], str(lower_md): ["[[[readme]]]"]}

    mocker.patch.object(check_slug_refs, "iter_source_files", return_value=[upper_md, lower_md])
    mocker.patch.object(Path, "read_text", lambda self, encoding="utf-8": "\n".join(content_by_str[str(self)]) + "\n")
    print_mock = mocker.patch("builtins.print")

    exit_code = check_slug_refs.main()

    output = "\n".join(call.args[0] for call in print_mock.call_args_list)
    assert exit_code == 1
    assert "duplicate declaration [[[readme]]]" in output


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


def test_main_ignores_a_triple_bracket_token_sharing_a_line_with_other_text(mocker: MockerFixture) -> None:
    """A `[[[doc#slug]]]`-shaped token is only a declaration when it is alone on its line.

    Prose can legitimately mention the triple-bracket syntax (e.g. explaining the convention)
    without that turning into a real declaration; the adjacent brackets also make it invisible to
    the double-bracket reference regex, so it isn't miscounted as a reference either.

    **Test steps:**

    * put `[[[plugins#overview]]]` mid-sentence, sharing its line with other text
    * verify `main()` finds zero declarations and zero references
    """
    other_md = check_slug_refs.SPECS_ROOT / "data-model.md"
    files = {other_md: ["See [[[plugins#overview]]] above for the declaration syntax."]}

    exit_code, output = run_main(mocker, files)

    assert exit_code == 0
    assert "0 declarations, 0 references, all resolve" in output


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
