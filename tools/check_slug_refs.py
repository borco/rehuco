"""Validate `[[doc#slug]]` / `[[appendices.doc#slug]]` cross-references across the repo.

A **declaration** is an occurrence that is the only thing on its line (the line under a spec
heading, e.g. ``[[plugins#field-toolkit]]``); every other occurrence is a **reference**. Checks:

- no `(doc, slug)` pair is declared more than once;
- every reference resolves to exactly one declaration.

Scans `docs/**/*.md` and every `.py` file under `apps/` and `packages/` (skipping the gitignored,
generated `*_ui.py` / `*_rc.py` files, which are never hand-edited and never carry these tokens).
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TOKEN_RE = re.compile(r"\[\[([a-zA-Z0-9_.-]+)#([a-zA-Z0-9-]+)\]\]")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
FENCE_RE = re.compile(r"^\s*```")


def strip_markdown_code(lines: list[str]) -> list[str]:
    """Blank out fenced code blocks and inline code spans so tokens shown as literal examples
    (e.g. `` `[[doc#slug]]` `` explaining the format) aren't mistaken for real references.

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

    for path in iter_source_files():
        rel = path.relative_to(REPO_ROOT)
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(strip_markdown_code(raw_lines), start=1):
            matches = list(TOKEN_RE.finditer(line))
            if not matches:
                continue
            is_declaration = len(matches) == 1 and line.strip() == matches[0].group(0)
            for match in matches:
                doc, slug = match.group(1), match.group(2)
                if is_declaration:
                    declarations.setdefault((doc, slug), []).append(f"{rel}:{lineno}")
                else:
                    references.append((doc, slug, str(rel), lineno))

    errors: list[str] = []

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
