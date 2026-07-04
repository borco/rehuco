"""Validate `[[doc#slug]]` / `[[appendices.doc#slug]]` cross-references across the repo.

A **declaration** is a triple-bracket token alone on its line (the line under a spec heading, e.g.
``[[[plugins#field-toolkit]]]``); every double-bracket occurrence elsewhere is a **reference**.
The extra bracket makes a declaration structurally distinct from a reference -- a wrapped
reference can never coincidentally look like one, however it lands on its line. A token may omit
`#slug` entirely (``[[[data-model]]]`` / ``[[data-model]]``) to declare/reference a whole document
rather than one of its headings -- every H1 carries one of these, for whole-chapter references
that don't belong to any single subsection. Checks:

- no `(doc, slug)` pair is declared more than once;
- every reference resolves to exactly one declaration;
- a declaration's `doc` component matches the spec file it's actually declared in.

Scans `docs/**/*.md`, the root `CLAUDE.md`, every `README.md`, and every `.py` file under `apps/`
and `packages/` (skipping the gitignored, generated `*_ui.py` / `*_rc.py` files, which are never
hand-edited and never carry these tokens). The file list comes from git (tracked files plus
untracked-but-not-gitignored ones), so gitignored/generated content (`.venv`, `__pycache__`, build
output) is never considered, while a brand-new file not yet `git add`-ed still is.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_ROOT = REPO_ROOT / "docs" / "specs"

DECL_LINE_RE = re.compile(r"^\[\[\[([a-zA-Z0-9_.-]+)(?:#([a-zA-Z0-9-]+))?\]\]\]$")
REF_TOKEN_RE = re.compile(r"(?<!\[)\[\[([a-zA-Z0-9_.-]+)(?:#([a-zA-Z0-9-]+))?\]\](?!\])")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
FENCE_RE = re.compile(r"^\s*```")


def strip_markdown_code(lines: list[str]) -> list[str]:
    """Blank out fenced code blocks and inline code spans so tokens shown as literal examples
    (e.g. `` `[[[doc#slug]]]` `` explaining the format) aren't mistaken for real references.

    :param lines: the file's lines, unmodified.
    :returns: the same number of lines, with code content replaced by blanks.
    """
    out = []
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else INLINE_CODE_RE.sub("", line))
    return out


def format_token(doc: str, slug: str | None, *, declaration: bool) -> str:
    """Render a `(doc, slug)` pair back into its bracketed token form, for error messages.

    :param doc: the document key.
    :param slug: the heading slug, or ``None`` for a whole-document token.
    :param declaration: ``True`` for the triple-bracket declaration form, ``False`` for a reference.
    :returns: e.g. ``[[[doc#slug]]]``, ``[[doc]]``.
    """
    open_brackets, close_brackets = ("[[[", "]]]") if declaration else ("[[", "]]")
    body = f"{doc}#{slug}" if slug else doc
    return f"{open_brackets}{body}{close_brackets}"


def expected_doc_key(path: Path) -> str | None:
    """The `doc` a declaration in this file must use, derived from its path under `docs/specs/`.

    :param path: absolute path to the file being scanned.
    :returns: e.g. ``"plugins"`` for `docs/specs/plugins.md`, ``"appendices.testing"`` for
        `docs/specs/appendices/testing.md`; ``None`` for anything outside `docs/specs/` (a
        declaration has no business appearing there at all).
    """
    try:
        rel = path.relative_to(SPECS_ROOT)
    except ValueError:
        return None
    if rel.parts[0] == "appendices":
        return f"appendices.{path.stem.lower()}"
    return path.stem.lower()


def iter_repo_files() -> list[Path]:
    """List every file git considers part of the working tree, as absolute paths.

    :returns: tracked files plus untracked-but-not-gitignored ones (``git ls-files --cached
        --others --exclude-standard``), so gitignored/generated content (`.venv`, `__pycache__`,
        build output) is never considered a source file, while a brand-new file a developer just
        created -- not yet `git add`-ed -- still is.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return [REPO_ROOT / rel for rel in result.stdout.split("\0") if rel]


def iter_source_files() -> list[Path]:
    """Return every file this checker should scan for `[[doc#slug]]` tokens.

    :returns: markdown files under `docs/`, the root `CLAUDE.md`, every `README.md`, plus `.py`
        files under `apps/`/`packages/` (excluding generated `*_ui.py`/`*_rc.py`).
    """
    files: list[Path] = []
    for path in iter_repo_files():
        rel = path.relative_to(REPO_ROOT)
        is_scanned_markdown = path.suffix == ".md" and (
            rel.parts[0] == "docs" or path.name in ("CLAUDE.md", "README.md")
        )
        is_scanned_python = (
            path.suffix == ".py"
            and rel.parts[0] in ("apps", "packages")
            and not path.name.endswith(("_ui.py", "_rc.py"))
        )
        if is_scanned_markdown or is_scanned_python:
            files.append(path)
    return files


def find_duplicate_declarations(declarations: dict[tuple[str, str | None], list[str]]) -> list[str]:
    """Report every `(doc, slug)` pair declared at more than one site.

    :param declarations: each declared `(doc, slug)` pair mapped to every `file:line` it appears at.
    :returns: one formatted error message per duplicate.
    """
    return [
        f"duplicate declaration {format_token(doc, slug, declaration=True)} at: {', '.join(sites)}"
        for (doc, slug), sites in declarations.items()
        if len(sites) > 1
    ]


def find_unresolved_references(
    references: list[tuple[str, str | None, str, int]],
    declarations: dict[tuple[str, str | None], list[str]],
) -> list[str]:
    """Report every reference whose `(doc, slug)` pair has no matching declaration.

    :param references: each reference token as `(doc, slug, file, line)`.
    :param declarations: every declared `(doc, slug)` pair, to check references against.
    :returns: one formatted error message per unresolved reference.
    """
    return [
        f"{rel}:{lineno}: {format_token(doc, slug, declaration=False)} has no declaration"
        for doc, slug, rel, lineno in references
        if (doc, slug) not in declarations
    ]


def main() -> int:
    """Scan the repo for `[[doc#slug]]` tokens and report duplicate/unresolved ones.

    :returns: process exit code -- 0 if every declaration is unique and every reference resolves.
    """
    declarations: dict[tuple[str, str | None], list[str]] = {}
    references: list[tuple[str, str | None, str, int]] = []
    errors: list[str] = []

    for path in iter_source_files():
        rel = path.relative_to(REPO_ROOT)
        expected_doc = expected_doc_key(path)
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(strip_markdown_code(raw_lines), start=1):
            decl_match = DECL_LINE_RE.match(line.strip())
            if decl_match:
                doc, slug = decl_match.group(1), decl_match.group(2)
                declarations.setdefault((doc, slug), []).append(f"{rel}:{lineno}")
                if doc != expected_doc:
                    errors.append(
                        f"{rel}:{lineno}: declaration {format_token(doc, slug, declaration=True)} should use "
                        f"doc-key '{expected_doc}' for this file"
                    )
                continue
            for match in REF_TOKEN_RE.finditer(line):
                doc, slug = match.group(1), match.group(2)
                references.append((doc, slug, str(rel), lineno))

    errors.extend(find_duplicate_declarations(declarations))
    errors.extend(find_unresolved_references(references, declarations))

    if errors:
        print(f"FAILED -- {len(errors)} issue(s):")
        for error in errors:
            print(f"  {error}")
        return 1

    print(f"OK -- {len(declarations)} declarations, {len(references)} references, all resolve.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
