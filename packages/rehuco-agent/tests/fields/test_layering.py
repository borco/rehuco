"""The field toolkit imports neither ``documents`` nor ``settings`` (#151, [[plugins#field-toolkit]]).

The toolkit owns the protocols those layers implement -- `FieldModel` for the view-model binding,
`ImageScanner` for screenshot resolution, and its own ``DescriptionRenderingSettings`` for Markdown
rendering -- so the dependency only ever points inward: ``documents``/``settings`` import ``fields``,
never the reverse. This import-linter-style test guards that seam against regressions.
"""

import ast
from pathlib import Path

import rehuco_agent.fields

FIELDS_PACKAGE = "rehuco_agent.fields"
FIELDS_DIR = Path(rehuco_agent.fields.__file__).parent
FORBIDDEN_ROOTS = ("rehuco_agent.documents", "rehuco_agent.settings")


def module_name(path: Path) -> str:
    """The dotted module name of a ``.py`` file under the fields package.

    :param path: the source file, under :data:`FIELDS_DIR`.
    :returns: its fully-qualified module name (a package's ``__init__`` yields the package itself).
    """
    parts = path.relative_to(FIELDS_DIR).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((FIELDS_PACKAGE, *parts))


def package_of(path: Path) -> str:
    """The ``__package__`` a relative import in ``path`` resolves against.

    :param path: the source file, under :data:`FIELDS_DIR`.
    :returns: the containing package's dotted name (the file itself when it is a package ``__init__``).
    """
    name = module_name(path)
    return name if path.name == "__init__.py" else name.rsplit(".", 1)[0]


def imported_modules(path: Path) -> set[str]:
    """Every absolute module name ``path`` imports, resolving relative imports against its package.

    :param path: the source file to scan.
    :returns: the fully-qualified targets of its ``import`` / ``from ... import`` statements.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    anchor = package_of(path).split(".")
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    targets.add(node.module)
            else:
                base = anchor[: len(anchor) - (node.level - 1)]
                targets.add(".".join((*base, *(node.module.split(".") if node.module else ()))))
    return targets


def is_forbidden(target: str) -> bool:
    """Whether ``target`` names a module under ``documents`` or ``settings``.

    :param target: an absolute module name.
    :returns: ``True`` when it is (or is under) a forbidden root.
    """
    return any(target == root or target.startswith(f"{root}.") for root in FORBIDDEN_ROOTS)


def test_fields_toolkit_does_not_import_documents_or_settings() -> None:
    """No module under ``rehuco_agent.fields`` imports from ``documents`` or ``settings`` (#151).

    **Test steps:**

    * walk every ``.py`` file in the field toolkit
    * resolve each import (relative imports against the file's own package) to an absolute module
    * verify none resolve under ``rehuco_agent.documents`` or ``rehuco_agent.settings``
    """
    violations = {
        f"{module_name(path)} -> {target}"
        for path in FIELDS_DIR.rglob("*.py")
        for target in imported_modules(path)
        if is_forbidden(target)
    }
    assert not violations, "fields toolkit imports upward into documents/settings:\n" + "\n".join(sorted(violations))
