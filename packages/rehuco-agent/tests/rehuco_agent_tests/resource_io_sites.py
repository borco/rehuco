"""Finds the calls that read or touch a resource's files directly (#415, [[nodes#access-seam]]).

An AST walk, so nothing is imported or run. It knows spellings, not types: ``.open`` on a ``Path`` and on a
``QBuffer`` look alike, so what it reports is a list of *candidates*, each named by file, enclosing scope and
call -- stable when a line moves -- for ``test_resource_io_guard.py`` to compare against its allowlist.

Two kinds of call are found: the file-system primitives themselves, and the calls into rehuco-core that do the
reading on the agent's behalf (:data:`CORE_IO_ENTRY_POINTS`) -- the sites a migration issue actually moves. A call
on an *instance* is out of reach, since only its spelling is known: ``self.__document.save()`` cannot be told from
``settings.save()``, so the model's own save path is not flagged; #416 replaces that path wholesale.
"""

import ast
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

PATH_METHODS: Final = frozenset(
    {
        "exists",
        "glob",
        "is_dir",
        "is_file",
        "iterdir",
        "lstat",
        "mkdir",
        "open",
        "read_bytes",
        "read_text",
        "rglob",
        "rmdir",
        "samefile",
        "scandir",
        "stat",
        "touch",
        "unlink",
        "walk",
        "write_bytes",
        "write_text",
    }
)
"""Method names that touch the file system whatever they are called on. ``replace`` and ``rename`` are left out:
``str.replace`` and ``RenameCoordinator.rename`` are far more common than the ``Path`` methods, and a move through
``os`` or ``shutil`` is caught."""

OS_CALLS: Final = frozenset(
    {
        "listdir",
        "lstat",
        "makedirs",
        "mkdir",
        "remove",
        "rename",
        "replace",
        "rmdir",
        "scandir",
        "stat",
        "unlink",
        "walk",
    }
)
"""The ``os`` functions that touch the file system."""

OS_PATH_CALLS: Final = frozenset({"exists", "getmtime", "getsize", "isdir", "isfile", "islink"})
"""The ``os.path`` functions that touch the file system."""

WHOLE_MODULES: Final = frozenset({"zipfile", "shutil"})
"""Modules every call into counts, bar :data:`PATH_LOOKUPS`."""

PATH_LOOKUPS: Final = frozenset({"shutil.which"})
"""Calls into :data:`WHOLE_MODULES` that search ``PATH`` and read no resource."""

QT_READERS: Final = frozenset({"QFile", "QImage", "QImageReader", "QPixmap"})
"""Qt classes that read a file when constructed from a path."""

NOT_FILE_OPENERS: Final = frozenset({"CatalogCache", "LogScope"})
"""Classes whose ``open`` classmethod opens something other than a file: a catalog cache or a log scope."""

CORE_IO_ENTRY_POINTS: Final = frozenset(
    {
        "borco_pyside.recycle_bin.recycle_bin",
        "rehuco_core.DEFAULT_DELETER.delete",
        "rehuco_core.DirectoryClassifier",
        "rehuco_core.GenerateChecksumsJob",
        "rehuco_core.RehuDocument.load",
        "rehuco_core.RemoveCatalogRootJob",
        "rehuco_core.RetireLegacyManifestJob",
        "rehuco_core.RootFolderLister",
        "rehuco_core.ScanCatalogRootJob",
        "rehuco_core.SweepChecksumsJob",
        "rehuco_core.TcImportJob",
        "rehuco_core.VerifyChecksumsJob",
        "rehuco_core.check_records",
        "rehuco_core.content_duration",
        "rehuco_core.content_size_on_disk",
        "rehuco_core.conversion_backups",
        "rehuco_core.convert_screenshot",
        "rehuco_core.convert_tc",
        "rehuco_core.delete_screenshot",
        "rehuco_core.discard_conversion_backups",
        "rehuco_core.enumerate_content_files",
        "rehuco_core.enumerate_content_images",
        "rehuco_core.forget_checksums",
        "rehuco_core.legacy_manifest_for",
        "rehuco_core.list_archive_images",
        "rehuco_core.load_checksum_record",
        "rehuco_core.load_tc",
        "rehuco_core.originals_to_back_up",
        "rehuco_core.other_record_stems",
        "rehuco_core.plan_tc_conversion",
        "rehuco_core.read_archive_facts",
        "rehuco_core.rehu_rename_conflict",
        "rehuco_core.renumber_screenshots",
        "rehuco_core.rename_rehu_resource",
        "rehuco_core.save_screenshot",
        "rehuco_core.scan_conversion_backups",
        "rehuco_core.scan_tc_screenshots",
        "rehuco_core.take_enclosing_claims",
    }
)
"""Calls into the libraries that read or touch a resource's files on the agent's behalf, spelled by their import
origin as :func:`tracked_imports` records it, so an alias matches. A class is named for the site that makes the
object that does the I/O (a job, a lister). Not here: a pure helper (path arithmetic, parsing, a freshness test), and
a write into the app's own folders (``stage_image``, ``prune_staged`` -- the staging folder is under the cache)."""

TRACKED_ROOTS: Final = frozenset({"borco_pyside", "os", "rehuco_core", *WHOLE_MODULES})
"""The modules whose imported names :func:`tracked_imports` records."""


@dataclass(frozen=True)
class Site:
    """One call that may read or touch a file directly.

    :param path: the source file, relative to the scanned folder, with ``/`` separators.
    :param scope: the dotted class and function names the call sits in, ``<module>`` outside any.
    :param call: how the call is spelled, e.g. ``.stat`` or ``zipfile.ZipFile``.
    :param line: where it is, for the failure message only -- never part of :attr:`key`.
    """

    path: str
    scope: str
    call: str
    line: int

    @property
    def key(self) -> str:
        """What an allowlist names this site by, so a moved line does not invalidate it.

        :returns: the file, scope and call joined by ``::``.
        """
        return f"{self.path}::{self.scope}::{self.call}"


def dotted_name(node: ast.expr) -> str | None:
    """The dotted spelling of a name or attribute chain.

    :param node: the expression to spell.
    :returns: e.g. ``os.path.exists``, or ``None`` when the chain does not start at a plain name.
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def tracked_imports(tree: ast.Module) -> dict[str, str]:
    """The names a module imports out of :data:`TRACKED_ROOTS`, so a call to one is recognized under any alias.

    ``rehuco_core`` re-exports its API at the package root, so a name imported from one of its submodules is recorded
    under the root spelling -- ``rehuco_core.load_tc`` whether it came from ``rehuco_core`` or
    ``rehuco_core.tc_document`` -- and :data:`CORE_IO_ENTRY_POINTS` cannot be sidestepped by a deeper import.

    :param tree: the parsed module.
    :returns: each local name mapped to its dotted origin, e.g. ``ZipFile`` to ``zipfile.ZipFile``.
    """
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module):
            continue
        root = node.module.split(".")[0]
        if root in TRACKED_ROOTS:
            origin = root if root == "rehuco_core" else node.module
            imported.update({(alias.asname or alias.name): f"{origin}.{alias.name}" for alias in node.names})
    return imported


def is_path_argument(call: ast.Call) -> bool:
    """Whether a Qt constructor call could be reading a file: one positional argument that is not a ``QSize``.

    ``QImage(path)`` reads; ``QImage(size, format)`` and ``QPixmap(QSize(...))`` allocate.

    :param call: a call to one of :data:`QT_READERS`.
    :returns: ``True`` when the call has the file-reading shape.
    """
    if len(call.args) != 1 or call.keywords:
        return False
    argument = call.args[0]
    return not (isinstance(argument, ast.Call) and dotted_name(argument.func) == "QSize")


def module_call(spelling: str) -> str | None:
    """Judge a call spelled through ``os``, ``zipfile`` or ``shutil``.

    :param spelling: the dotted spelling, e.g. ``os.path.exists``.
    :returns: the spelling when it touches the file system, otherwise ``None``.
    """
    root, _, rest = spelling.partition(".")
    if root in WHOLE_MODULES:
        return None if spelling in PATH_LOOKUPS else spelling
    if root == "os":
        owner, _, name = rest.rpartition(".")
        if (owner == "" and name in OS_CALLS) or (owner == "path" and name in OS_PATH_CALLS):
            return spelling
    return None


def classify_name(call: ast.Call, name: str, imported: dict[str, str]) -> str | None:
    """Judge a call made through a bare name.

    :param call: the call to judge.
    :param name: the name it calls.
    :param imported: the module's :func:`tracked_imports`.
    :returns: its spelling when it touches a file, otherwise ``None``.
    """
    if name == "open":
        return name
    if name in imported:
        origin = imported[name]
        return origin if origin in CORE_IO_ENTRY_POINTS else module_call(origin)
    return name if name in QT_READERS and is_path_argument(call) else None


def classify_attribute(func: ast.Attribute, imported: dict[str, str]) -> str | None:
    """Judge a call made through an attribute.

    :param func: the attribute being called.
    :param imported: the module's :func:`tracked_imports`.
    :returns: its spelling when it touches a file, otherwise ``None``.
    """
    spelling = dotted_name(func)
    if isinstance(func.value, ast.Name) and func.value.id in imported:
        spelling = f"{imported[func.value.id]}.{func.attr}"
    if spelling in CORE_IO_ENTRY_POINTS:
        return spelling
    if spelling is not None and (found := module_call(spelling)):
        return found
    if isinstance(func.value, ast.Name) and func.value.id in NOT_FILE_OPENERS:
        return None
    return f".{func.attr}" if func.attr in PATH_METHODS else None


def classify(call: ast.Call, imported: dict[str, str]) -> str | None:
    """Name the direct file access a call makes, if it makes one.

    :param call: the call to judge.
    :param imported: the module's :func:`tracked_imports`.
    :returns: its spelling, or ``None`` when it is not one.
    """
    func = call.func
    if isinstance(func, ast.Name):
        return classify_name(call, func.id, imported)
    return classify_attribute(func, imported) if isinstance(func, ast.Attribute) else None


def walk_calls(node: ast.AST, scope: tuple[str, ...], imported: dict[str, str]) -> Iterator[tuple[str, str, int]]:
    """Every direct file access under ``node``, with the scope it sits in.

    :param node: where to look.
    :param scope: the class and function names ``node`` is already inside.
    :param imported: the module's :func:`tracked_imports`.
    :returns: ``(scope, call, line)`` for each one, in source order.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call) and (found := classify(child, imported)):
            yield ".".join(scope) or "<module>", found, child.lineno
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield from walk_calls(child, (*scope, child.name), imported)
        else:
            yield from walk_calls(child, scope, imported)


def scan_source(source: str, path: str) -> list[Site]:
    """The direct file accesses in one module's source.

    :param source: the module's text.
    :param path: what to call the module in each :class:`Site`.
    :returns: its sites, in source order.
    """
    tree = ast.parse(source)
    imported = tracked_imports(tree)
    return [Site(path, scope, call, line) for scope, call, line in walk_calls(tree, (), imported)]


def scan_folder(folder: Path) -> list[Site]:
    """The direct file accesses in every hand-written module under a folder.

    :param folder: the package folder to scan; generated ``*_ui.py`` and ``*_rc.py`` modules are skipped.
    :returns: its sites, ordered by file then line.
    """
    sites: list[Site] = []
    for path in sorted(folder.rglob("*.py")):
        if not path.name.endswith(("_ui.py", "_rc.py")):
            sites.extend(scan_source(path.read_text(encoding="utf-8"), path.relative_to(folder).as_posix()))
    return sites


def count_by_key(sites: list[Site]) -> Counter[str]:
    """Tally sites by :attr:`Site.key`, since one scope may make the same call twice.

    :param sites: what :func:`scan_folder` found.
    :returns: how many sites each key has.
    """
    return Counter(site.key for site in sites)


def compare_with_allowed(sites: list[Site], allowed: dict[str, int]) -> tuple[list[str], list[str]]:
    """Set the sites found against the counts an allowlist grants.

    :param sites: what :func:`scan_folder` found.
    :param allowed: how many sites each :attr:`Site.key` may have.
    :returns: the sites beyond what is allowed, as ``path:line: call`` lines, and the allowlist keys that grant more
        than there are -- stale entries, which a migration must delete so the list can only shrink.
    """
    found = count_by_key(sites)
    seen: Counter[str] = Counter()
    unlisted: list[str] = []
    for site in sites:
        seen[site.key] += 1
        if seen[site.key] > allowed.get(site.key, 0):
            unlisted.append(f"{site.path}:{site.line}: {site.call} in {site.scope}")
    stale = [key for key, count in allowed.items() if found[key] < count]
    return unlisted, stale
