"""A tool for the external-tool tests to describe, and a way to lay out its install on disk (#521)."""

from pathlib import Path
from typing import Final, override

from rehuco_core import BlockedVersion, ToolDescriptor, Version
from rehuco_core.external_tools.tool_descriptor import EXECUTABLE_SUFFIX


class SampleTool(ToolDescriptor):
    """A tool with a minimum, a tested ceiling and one blocked version, in a place no OS keeps it."""

    ID = "sample"
    LABEL = "Sample"
    PURPOSE = "Tests."
    FEATURES = "None."
    NOT_BUNDLED_BECAUSE = "It is a test."
    DOCS_ANCHOR = "sample"
    EXECUTABLES = ("alpha", "beta")
    MINIMUM = (4, 0)
    NEWEST_TESTED = (6, 2)
    BLOCKLIST = (BlockedVersion((5, 1), "5.1 crashes on start."),)

    @override
    def search_patterns(self) -> tuple[tuple[str, str], ...]:
        return ()

    @override
    def read_version(self, folder: Path) -> Version | None:
        return None


SAMPLE: Final = SampleTool()


def make_install(folder: Path, names: tuple[str, ...] = SampleTool.EXECUTABLES) -> Path:
    """Create the executables of an install.

    :param folder: where to create them.
    :param names: which ones.
    :returns: the folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / f"{name}{EXECUTABLE_SUFFIX}").write_bytes(b"")
    return folder
