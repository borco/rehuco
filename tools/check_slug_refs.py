"""Validate `[[doc#slug]]` / `[[appendices.doc#slug]]` cross-references across the repo.

A **declaration** is a triple-bracket token alone on its line (the line under a spec heading, e.g.
``[[[plugins#field-toolkit]]]``); every double-bracket occurrence elsewhere is a **reference**.
The extra bracket makes a declaration structurally distinct from a reference -- a wrapped
reference can never coincidentally look like one, however it lands on its line. Checks:

- no `(doc, slug)` pair is declared more than once;
- every reference resolves to exactly one declaration;
- a declaration's `doc` component matches the spec file it's actually declared in.

Scans `docs/**/*.md` and every `.py` file under `apps/` and `packages/` (skipping the gitignored,
generated `*_ui.py` / `*_rc.py` files, which are never hand-edited and never carry these tokens).
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_ROOT = REPO_ROOT / "docs" / "specs"

DECL_LINE_RE = re.compile(r"^\[\[\[([a-zA-Z0-9_.-]+)#([a-zA-Z0-9-]+)\]\]\]$")
REF_TOKEN_RE = re.compile(r"(?<!\[)\[\[([a-zA-Z0-9_.-]+)#([a-zA-Z0-9-]+)\]\](?!\])")
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
        return f"appendices.{path.stem}"
    return path.stem


def iter_source_files() -> list[Path]:
    """Return every file this checker should scan for `[[doc#slug]]` tokens.

    :returns: markdown files under `docs/`, plus `.py` files under `apps/`/`packages/`
        (excluding generated `*_ui.py`/`*_rc.py`).
    """
    files = list((REPO_ROOT / "docs").rglob("*.md"))
    for base in ("apps", "packages"):
        for path in (REPO_ROOT / base).rglob("*.py"):
            if path.name.endswith(("_ui.py", "_rc.py")):
                continue
            files.append(path)
    return files


def main() -> int:
    """Scan the repo for `[[doc#slug]]` tokens and report duplicate/unresolved ones.

    :returns: process exit code -- 0 if every declaration is unique and every reference resolves.
    """
    declarations: dict[tuple[str, str], list[str]] = {}
    references: list[tuple[str, str, str, int]] = []
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
                        f"{rel}:{lineno}: declaration [[[{doc}#{slug}]]] should use doc-key "
                        f"'{expected_doc}' for this file"
                    )
                continue
            for match in REF_TOKEN_RE.finditer(line):
                doc, slug = match.group(1), match.group(2)
                references.append((doc, slug, str(rel), lineno))

    for (doc, slug), sites in declarations.items():
        if len(sites) > 1:
            errors.append(f"duplicate declaration [[{doc}#{slug}]] at: {', '.join(sites)}")

    for doc, slug, rel, lineno in references:
        if (doc, slug) not in declarations:
            errors.append(f"{rel}:{lineno}: [[{doc}#{slug}]] has no declaration")

    if errors:
        print(f"FAILED -- {len(errors)} issue(s):")
        for error in errors:
            print(f"  {error}")
        return 1

    print(f"OK -- {len(declarations)} declarations, {len(references)} references, all resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
