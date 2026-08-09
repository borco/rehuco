"""Tests for the dry-run `.tc` bulk-conversion plan -- what converting a tree would do, without
touching anything (#191, [[acquisition-tooling#tc-to-rehu]])."""

from pathlib import Path
from typing import Any, Final

from fake_directories import FakeDirEntry, FakeScandir
from pytest_mock import MockerFixture
from rehuco_core import ScreenshotRename, TcConversionTreePlan, plan_tc_conversion

ROOT: Final = Path("/fake/library")

DEFAULT_YAML: Final = "type: Tutorial\ntitle: Some Title\n"
DEFAULT_MTIME: Final = 1700000000.0


def mock_environment(  # pylint: disable=too-many-arguments,too-many-locals
    mocker: MockerFixture,
    *,
    tc_files: list[str],
    directories: list[str] | None = None,
    unreadable: list[str] | None = None,
    unreadable_files: list[str] | None = None,
    other_files: list[str] | None = None,
    yaml_by_path: dict[Path, str] | None = None,
    existing: frozenset[Path] = frozenset(),
    mtimes: dict[Path, float] | None = None,
    renames_by_directory: dict[Path, list[ScreenshotRename]] | None = None,
) -> dict[str, Any]:
    """Mock a tree of `.tc` resources under :data:`ROOT` and every filesystem/scan call the planner makes.

    :param mocker: pytest-mock fixture.
    :param tc_files: fake `.tc` paths relative to :data:`ROOT`, ``/``-separated.
    :param directories: fake directory paths relative to :data:`ROOT`; a `.tc` file's own parent need
        not be listed here, only directories the walk must actually descend into.
    :param unreadable: fake directory paths whose listing should raise ``OSError``.
    :param unreadable_files: fake `.tc` paths whose read should raise ``OSError`` -- a file gone away
        between the listing and the read, or one the mount will not serve.
    :param other_files: fake regular-file paths relative to :data:`ROOT` that are neither `.tc` files
        nor directories -- a resource's screenshots and other bookkeeping, which the walk must ignore.
    :param yaml_by_path: each `.tc` path's raw YAML text; defaults to :data:`DEFAULT_YAML`.
    :param existing: paths that should report as already existing on disk (a target `.rehu`, a stale
        `.orig` backup, ...).
    :param mtimes: each `.tc` path's mtime; defaults to :data:`DEFAULT_MTIME`.
    :param renames_by_directory: each resource directory's screenshot scan result; defaults to none.
    :returns: the created mocks, keyed by what they stand in for.
    """
    offline = {ROOT / name for name in unreadable or []}
    listing: dict[Path, list[FakeDirEntry]] = {ROOT: []}
    for name in directories or []:
        path = ROOT / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name, directory=True))
        listing.setdefault(path, [])
    for name in tc_files:
        path = ROOT / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name))
    for name in other_files or []:
        path = ROOT / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name))

    def scandir(directory: Path) -> FakeScandir:
        if Path(directory) in offline:
            raise OSError(directory)
        if Path(directory) not in listing:
            raise FileNotFoundError(directory)
        return FakeScandir(listing[Path(directory)])

    offline_files = {ROOT / name for name in unreadable_files or []}

    def read_text(self: Path, **_kw: Any) -> str:
        if self in offline_files:
            raise OSError(self)
        return (yaml_by_path or {}).get(self, DEFAULT_YAML)

    mocker.patch.object(Path, "read_text", autospec=True, side_effect=read_text)
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self in existing)
    mocker.patch.object(
        Path,
        "stat",
        autospec=True,
        side_effect=lambda self: mocker.MagicMock(st_mtime=(mtimes or {}).get(self, DEFAULT_MTIME)),
    )
    return {
        "scandir": mocker.patch("rehuco_core.tc_conversion_plan.os.scandir", side_effect=scandir),
        "scan": mocker.patch(
            "rehuco_core.tc_conversion_plan.scan_tc_screenshots",
            side_effect=lambda directory, stem: (renames_by_directory or {}).get(directory, []),
        ),
        "rename": mocker.patch.object(Path, "rename", autospec=True),
        "unlink": mocker.patch.object(Path, "unlink", autospec=True),
    }


# region What the walk finds


def test_a_tree_of_tc_resources_produces_one_plan_record_each_and_touches_nothing(mocker: MockerFixture) -> None:
    """A tree with several `.tc` resources produces one plan record each, and no file is created or
    modified.

    **Test steps:**

    * mock a tree with two directory-scoped `.tc` resources
    * plan the whole tree
    * verify one record per resource, each carrying the `.tc`/`.rehu` paths, and that nothing was
      renamed or unlinked
    """
    mocks = mock_environment(mocker, tc_files=["a/info.tc", "b/info.tc"], directories=["a", "b"])

    plan = plan_tc_conversion(ROOT)

    assert [r.tc_path for r in plan.resources] == [ROOT / "a/info.tc", ROOT / "b/info.tc"]
    assert [r.rehu_path for r in plan.resources] == [ROOT / "a/info.rehu", ROOT / "b/info.rehu"]
    assert plan.root == ROOT
    assert not plan.unreadable
    mocks["rename"].assert_not_called()
    mocks["unlink"].assert_not_called()


def test_a_directory_holding_a_tc_is_still_descended_past(mocker: MockerFixture) -> None:
    """A directory containing a `.tc` is a resource, but a nested `.tc` beneath it is not a scan
    boundary and is still found -- matching `rehuco_core.rehu_catalog.CatalogScanner` (#252).

    **Test steps:**

    * mock a resource directory whose own subdirectory also holds a `.tc`
    * plan the tree
    * verify both the outer and the nested resource are found
    """
    mock_environment(mocker, tc_files=["a/info.tc", "a/sub/nested.tc"], directories=["a", "a/sub"])

    plan = plan_tc_conversion(ROOT)

    assert [r.tc_path for r in plan.resources] == [ROOT / "a/info.tc", ROOT / "a/sub/nested.tc"]


def test_a_tc_at_the_root_still_plans_the_tree_beneath_it(mocker: MockerFixture) -> None:
    """A `.tc` sitting at the walk's own root -- a template stub, say -- does not stop the walk from
    finding every resource beneath it (#252).

    **Test steps:**

    * mock a `.tc` at the root and another resource in a subdirectory
    * plan the tree
    * verify both are found
    """
    mock_environment(mocker, tc_files=["info.tc", "a/info.tc"], directories=["a"])

    plan = plan_tc_conversion(ROOT)

    assert [r.tc_path for r in plan.resources] == [ROOT / "a/info.tc", ROOT / "info.tc"]


def test_a_collection_plans_the_parent_and_every_member(mocker: MockerFixture) -> None:
    """A tc4 collection -- a parent record over member directories -- plans the parent **and** every
    member, since a collection is the one structure in tc4 that nests by design (#252).

    **Test steps:**

    * mock a collection `.tc` with two member directories, each holding their own `.tc`
    * plan the tree
    * verify the parent and both members are all found
    """
    mock_environment(
        mocker,
        tc_files=["Foo/info.tc", "Foo/Part 1/info.tc", "Foo/Part 2/info.tc"],
        directories=["Foo", "Foo/Part 1", "Foo/Part 2"],
    )

    plan = plan_tc_conversion(ROOT)

    assert {r.tc_path for r in plan.resources} == {
        ROOT / "Foo/info.tc",
        ROOT / "Foo/Part 1/info.tc",
        ROOT / "Foo/Part 2/info.tc",
    }


def test_an_unrelated_file_is_neither_a_resource_nor_a_reason_to_stop(mocker: MockerFixture) -> None:
    """A regular file that is not a `.tc` -- a screenshot, a checksum record, anything else a resource's
    directory holds -- is not a resource and does not block the walk from finding the real one.

    **Test steps:**

    * mock a resource directory that also holds an unrelated file
    * plan the tree
    * verify only the `.tc` is found
    """
    mock_environment(mocker, tc_files=["a/info.tc"], directories=["a"], other_files=["a/cover.jpg"])

    plan = plan_tc_conversion(ROOT)

    assert [r.tc_path for r in plan.resources] == [ROOT / "a/info.tc"]


def test_several_resources_in_the_root_itself_are_all_found(mocker: MockerFixture) -> None:
    """A folder of file-scoped `.tc` resources (not every catalog nests one per subdirectory) is a
    folder of resources, not one.

    **Test steps:**

    * mock two `.tc` files sitting directly in the root
    * plan the tree
    * verify both are found
    """
    mock_environment(mocker, tc_files=["foo.tc", "bar.tc"])

    plan = plan_tc_conversion(ROOT)

    assert {r.tc_path for r in plan.resources} == {ROOT / "foo.tc", ROOT / "bar.tc"}


def test_the_rename_plan_matches_the_screenshot_scan_for_the_same_directory(mocker: MockerFixture) -> None:
    """The rename plan in the record matches what `scan_tc_screenshots` returns for the same directory.

    **Test steps:**

    * mock a screenshot scan result for a resource's directory
    * plan the tree
    * verify the record's `renames` is exactly that result
    """
    renames = [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",))]
    mock_environment(mocker, tc_files=["a/info.tc"], directories=["a"], renames_by_directory={ROOT / "a": renames})

    plan = plan_tc_conversion(ROOT)

    assert plan.resources[0].renames == tuple(renames)


def test_an_offline_branch_costs_its_own_subtree_and_is_named(mocker: MockerFixture) -> None:
    """A directory that will not list -- an away mount branch -- is reported rather than aborting the
    whole walk ([[mounts-and-storage#offline-mounts]]).

    **Test steps:**

    * mock one resource directory and one unreadable directory
    * plan the tree
    * verify the reachable resource is still found and the unreadable directory is named
    """
    mock_environment(mocker, tc_files=["a/info.tc"], directories=["a", "away"], unreadable=["away"])

    plan = plan_tc_conversion(ROOT)

    assert [r.tc_path for r in plan.resources] == [ROOT / "a/info.tc"]
    assert plan.unreadable == (ROOT / "away",)


def test_a_malformed_tc_costs_its_own_record_and_is_named(mocker: MockerFixture) -> None:
    """A `.tc` that will not parse is reported as unreadable rather than aborting the whole plan --
    the single-document path refuses it into a locked stub, and a bulk dry-run over thousands of
    resources has even less business crashing over one.

    **Test steps:**

    * mock two resources, one holding unparseable YAML
    * plan the tree
    * verify the good resource is still planned and the bad `.tc` is named as unreadable
    """
    bad = ROOT / "a/info.tc"
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc"],
        directories=["a", "b"],
        yaml_by_path={bad: "tags: [unterminated"},
    )

    plan = plan_tc_conversion(ROOT)

    assert [r.tc_path for r in plan.resources] == [ROOT / "b/info.tc"]
    assert plan.unreadable == (bad,)


def test_a_tc_that_will_not_read_costs_its_own_record_and_is_named(mocker: MockerFixture) -> None:
    """A `.tc` whose read raises -- gone between the listing and the read, or a mount refusing the
    file -- is reported the same way as one that will not parse.

    **Test steps:**

    * mock two resources, one whose `.tc` read raises ``OSError``
    * plan the tree
    * verify the good resource is still planned and the unreadable `.tc` is named
    """
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc"],
        directories=["a", "b"],
        unreadable_files=["a/info.tc"],
    )

    plan = plan_tc_conversion(ROOT)

    assert [r.tc_path for r in plan.resources] == [ROOT / "b/info.tc"]
    assert plan.unreadable == (ROOT / "a/info.tc",)


def test_progress_reports_a_running_count(mocker: MockerFixture) -> None:
    """The walk reports a running count as it goes, since a real catalog is thousands of resources.

    **Test steps:**

    * mock three resources
    * plan the tree with a progress callback
    * verify it was called once per resource with an increasing count
    """
    mock_environment(mocker, tc_files=["a/info.tc", "b/info.tc", "c/info.tc"], directories=["a", "b", "c"])
    progress = mocker.Mock()

    plan_tc_conversion(ROOT, progress=progress)

    assert progress.call_args_list == [mocker.call(1), mocker.call(2), mocker.call(3)]


# endregion

# region Flags


def test_tie_break_fires_when_a_slot_has_more_than_one_recognized_file(mocker: MockerFixture) -> None:
    """`tie_break` fires when two or more files resolved to the same slot, and not otherwise.

    **Test steps:**

    * mock one directory whose screenshot scan ties two files onto one slot, and one directory with no
      tie
    * plan the tree
    * verify only the tied resource is flagged
    """
    tied = [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg", "sample-00.png"))]
    clean = [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",))]
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc"],
        directories=["a", "b"],
        renames_by_directory={ROOT / "a": tied, ROOT / "b": clean},
    )

    plan = plan_tc_conversion(ROOT)

    by_path = {r.tc_path: r for r in plan.resources}
    assert by_path[ROOT / "a/info.tc"].tie_break is True
    assert by_path[ROOT / "b/info.tc"].tie_break is False


def test_rehu_exists_blocks_the_resource(mocker: MockerFixture) -> None:
    """`rehu_exists` fires when the target `.rehu` already exists, and the resource reads as blocked
    rather than convertible.

    **Test steps:**

    * mock a resource whose target `.rehu` already sits on disk
    * plan the tree
    * verify `rehu_exists` and `blocked` are both true
    """
    mock_environment(mocker, tc_files=["a/info.tc"], directories=["a"], existing=frozenset({ROOT / "a/info.rehu"}))

    plan = plan_tc_conversion(ROOT)

    assert plan.resources[0].rehu_exists is True
    assert plan.resources[0].blocked is True


def test_stale_backup_blocks_the_resource(mocker: MockerFixture) -> None:
    """`stale_backup` fires when a `.orig` sibling already exists, and the resource reads as blocked.

    **Test steps:**

    * mock a resource whose `.tc` already has a stale `.orig` backup beside it
    * plan the tree
    * verify `stale_backup` and `blocked` are both true
    """
    mock_environment(mocker, tc_files=["a/info.tc"], directories=["a"], existing=frozenset({ROOT / "a/info.tc.orig"}))

    plan = plan_tc_conversion(ROOT)

    assert plan.resources[0].stale_backup is True
    assert plan.resources[0].blocked is True


def test_size_unparsed_fires_when_a_carried_size_will_not_parse(mocker: MockerFixture) -> None:
    """`size_unparsed` fires when the `.tc` carries `original_size`/`current_size` but the value would
    not parse, and not when it parses cleanly.

    **Test steps:**

    * mock a `.tc` whose `original_size` is an unparseable string, and one whose value is a plain int
    * plan the tree
    * verify only the unparseable one is flagged
    """
    bad = ROOT / "a/info.tc"
    good = ROOT / "b/info.tc"
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc"],
        directories=["a", "b"],
        yaml_by_path={
            bad: "type: Tutorial\ntitle: X\noriginal_size: not-a-size\n",
            good: "type: Tutorial\ntitle: X\noriginal_size: 100\n",
        },
    )

    plan = plan_tc_conversion(ROOT)

    by_path = {r.tc_path: r for r in plan.resources}
    assert by_path[bad].size_unparsed is True
    assert by_path[good].size_unparsed is False


def test_duration_present_fires_only_when_the_mapped_block_carries_original_duration(mocker: MockerFixture) -> None:
    """`duration_present` fires when the mapped payload carries `original_duration` -- leaked from tc4's
    own `duration`, advisory until a real scan overwrites it.

    **Test steps:**

    * mock a Tutorial `.tc` carrying a `duration` and a Collection `.tc` (no plugin block at all)
    * plan the tree
    * verify only the Tutorial resource is flagged
    """
    with_duration = ROOT / "a/info.tc"
    no_block = ROOT / "b/info.tc"
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc"],
        directories=["a", "b"],
        yaml_by_path={
            with_duration: "type: Tutorial\ntitle: X\nduration: 3600\n",
            no_block: "type: Collection\ntitle: X\nduration: 3600\n",
        },
    )

    plan = plan_tc_conversion(ROOT)

    by_path = {r.tc_path: r for r in plan.resources}
    assert by_path[with_duration].duration_present is True
    assert by_path[no_block].duration_present is False


def test_unmapped_keys_names_keys_the_mapper_does_not_consume(mocker: MockerFixture) -> None:
    """`unmapped_keys` names `.tc` keys the mapper does not consume, and is empty when every key is
    recognized.

    **Test steps:**

    * mock a `.tc` carrying an unrecognized key, and one carrying only recognized keys
    * plan the tree
    * verify the unrecognized key is named for the first and nothing is named for the second
    """
    junk = ROOT / "a/info.tc"
    clean = ROOT / "b/info.tc"
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc"],
        directories=["a", "b"],
        yaml_by_path={
            junk: "type: Tutorial\ntitle: X\nsome_unknown_field: 1\n",
            clean: "type: Tutorial\ntitle: X\n",
        },
    )

    plan = plan_tc_conversion(ROOT)

    by_path = {r.tc_path: r for r in plan.resources}
    assert by_path[junk].unmapped_keys == ("some_unknown_field",)
    assert by_path[clean].unmapped_keys == ()


def test_suspect_mtime_fires_on_a_cluster_of_near_identical_timestamps(mocker: MockerFixture) -> None:
    """`suspect_mtime` fires on a wall of near-identical timestamps -- the signature of a bulk restore
    clobbering mtimes -- and not on a resource whose timestamp sits well apart from the rest.

    **Test steps:**

    * mock three resources whose mtimes fall inside one minute of each other, and a fourth an hour away
    * plan the tree
    * verify the clustered three are all flagged and the lone one is not
    """
    clustered = [ROOT / f"{name}/info.tc" for name in ("a", "b", "c")]
    alone = ROOT / "d/info.tc"
    mtimes = {
        clustered[0]: 1700000000.0,
        clustered[1]: 1700000020.0,
        clustered[2]: 1700000040.0,
        alone: 1700003700.0,
    }
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc", "c/info.tc", "d/info.tc"],
        directories=["a", "b", "c", "d"],
        mtimes=mtimes,
    )

    plan = plan_tc_conversion(ROOT)

    by_path = {r.tc_path: r for r in plan.resources}
    assert all(by_path[path].suspect_mtime for path in clustered)
    assert by_path[alone].suspect_mtime is False


# endregion

# region Summary counts


def test_summary_counts_match_the_record_set(mocker: MockerFixture) -> None:
    """Summary counts (`clean`/`flagged`/`blocked`) match the record set, and a blocked resource is
    reported as blocked, not as convertible.

    **Test steps:**

    * mock one clean resource, one flagged-but-convertible resource, and one blocked resource
    * plan the tree
    * verify each bucket's count and that they sum to the total
    """
    flagged_path = ROOT / "b/info.tc"
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc", "c/info.tc"],
        directories=["a", "b", "c"],
        yaml_by_path={flagged_path: "type: Tutorial\ntitle: X\nsome_unknown_field: 1\n"},
        existing=frozenset({ROOT / "c/info.rehu"}),
        # spread well apart so the mtime-cluster heuristic does not add its own flag
        mtimes={ROOT / "a/info.tc": 1700000000.0, ROOT / "b/info.tc": 1700010000.0, ROOT / "c/info.tc": 1700020000.0},
    )

    plan = plan_tc_conversion(ROOT)

    assert isinstance(plan, TcConversionTreePlan)
    assert plan.clean == 1
    assert plan.flagged == 1
    assert plan.blocked == 1
    assert plan.clean + plan.flagged + plan.blocked == len(plan.resources)
    by_path = {r.tc_path: r for r in plan.resources}
    assert by_path[ROOT / "c/info.tc"].blocked is True


# endregion

# region The manifest a conversion would carry forward


def test_a_same_stem_manifest_is_what_the_conversion_would_seed_from(mocker: MockerFixture) -> None:
    """The wizard's *verify or baseline* answer, taken off a listing the walk already read (#256).

    **Test steps:**

    * mock a resource holding an `info.sfv` and one holding no manifest at all
    * plan the tree
    * verify only the first names a manifest
    """
    mock_environment(
        mocker,
        tc_files=["a/info.tc", "b/info.tc"],
        directories=["a", "b"],
        other_files=["a/info.sfv", "b/cover.jpg"],
    )

    by_path = {r.tc_path: r for r in plan_tc_conversion(ROOT).resources}

    assert by_path[ROOT / "a/info.tc"].legacy_manifest == ROOT / "a/info.sfv"
    assert by_path[ROOT / "b/info.tc"].legacy_manifest is None


def test_an_entry_that_is_neither_a_file_nor_a_directory_is_passed_over(mocker: MockerFixture) -> None:
    """The walk now reads every name rather than only the `.tc` ones, so what it skips is worth pinning.

    **Test steps:**

    * mock a root holding one entry that is neither a regular file nor a directory
    * plan the tree
    * verify it found no resource and reported nothing unreadable
    """
    mocker.patch(
        "rehuco_core.tc_conversion_plan.os.scandir",
        side_effect=lambda _directory: FakeScandir([FakeDirEntry("live.sock", regular=False)]),
    )

    plan = plan_tc_conversion(ROOT)

    assert not plan.resources
    assert not plan.unreadable


def test_a_manifest_under_another_stem_is_not_this_resource_s(mocker: MockerFixture) -> None:
    """Same-stem is what makes it this record's, the rule the seed itself applies (#243).

    **Test steps:**

    * mock a resource whose directory holds a manifest under an unrelated stem
    * plan the tree
    * verify the resource names none
    """
    mock_environment(mocker, tc_files=["a/info.tc"], directories=["a"], other_files=["a/backup.sfv"])

    assert plan_tc_conversion(ROOT).resources[0].legacy_manifest is None


def test_the_strongest_readable_manifest_is_the_one_named(mocker: MockerFixture) -> None:
    """One manifest is read, by a fixed suffix precedence -- and the plan says which before anything runs.

    **Test steps:**

    * mock a resource holding both an `info.sfv` and an `info.md5`
    * plan the tree
    * verify the stronger suffix is the one named
    """
    mock_environment(mocker, tc_files=["a/info.tc"], directories=["a"], other_files=["a/info.sfv", "a/info.md5"])

    assert plan_tc_conversion(ROOT).resources[0].legacy_manifest == ROOT / "a/info.md5"


# endregion

# region Stranded manifests (#259)


def test_a_converted_resource_still_carrying_its_manifest_is_reported(mocker: MockerFixture) -> None:
    """The state hand-conversion left behind, found off the listing the walk already reads.

    **Test steps:**

    * mock a directory holding an `info.rehu`, its `info.checksum` and a live `info.sfv`
    * plan the tree
    * verify it is reported as stranded, naming the manifest, and is not a conversion
    """
    mock_environment(
        mocker,
        tc_files=[],
        directories=["a"],
        other_files=["a/info.rehu", "a/info.checksum", "a/info.sfv"],
    )

    plan = plan_tc_conversion(ROOT)

    assert not plan.resources
    assert [(row.rehu_path, row.manifest) for row in plan.stranded] == [(ROOT / "a/info.rehu", ROOT / "a/info.sfv")]
    assert plan.stranded[0].record_path == ROOT / "a/info.checksum"


def test_a_converted_resource_with_no_record_yet_is_not_stranded(mocker: MockerFixture) -> None:
    """Nothing has absorbed the claim, so a plain verify still seeds and retires it (#243).

    **Test steps:**

    * mock a directory holding an `info.rehu` and an `info.sfv`, with no `.checksum`
    * plan the tree
    * verify nothing was reported
    """
    mock_environment(mocker, tc_files=[], directories=["a"], other_files=["a/info.rehu", "a/info.sfv"])

    assert not plan_tc_conversion(ROOT).stranded


def test_a_converted_resource_whose_manifest_was_retired_is_not_stranded(mocker: MockerFixture) -> None:
    """A retired manifest is a backup, not a manifest -- which is what retiring it was for.

    **Test steps:**

    * mock a directory holding an `info.rehu`, an `info.checksum` and an `info.sfv.orig`
    * plan the tree
    * verify nothing was reported
    """
    mock_environment(
        mocker,
        tc_files=[],
        directories=["a"],
        other_files=["a/info.rehu", "a/info.checksum", "a/info.sfv.orig"],
    )

    assert not plan_tc_conversion(ROOT).stranded


def test_an_unconverted_resource_gets_a_conversion_row_and_no_stranded_one(mocker: MockerFixture) -> None:
    """The conversion carries the manifest forward itself; a second job would race it.

    **Test steps:**

    * mock a directory holding an `info.tc`, its `info.checksum` and a live `info.sfv`
    * plan the tree
    * verify it is one conversion and nothing stranded
    """
    mock_environment(
        mocker,
        tc_files=["a/info.tc"],
        directories=["a"],
        other_files=["a/info.checksum", "a/info.sfv"],
    )

    plan = plan_tc_conversion(ROOT)

    assert len(plan.resources) == 1
    assert not plan.stranded


def test_a_stranded_manifest_naming_an_unhashable_algorithm_is_passed_over(mocker: MockerFixture) -> None:
    """Nothing would read it, so nothing here would absorb or retire it either.

    **Test steps:**

    * mock a converted resource whose only manifest is an `info.sha1` this build cannot hash
    * plan the tree
    * verify nothing was reported
    """
    mock_environment(
        mocker,
        tc_files=[],
        directories=["a"],
        other_files=["a/info.rehu", "a/info.checksum", "a/info.sha1"],
    )

    assert not plan_tc_conversion(ROOT).stranded


def test_stranded_rows_are_sorted_by_path(mocker: MockerFixture) -> None:
    """A walk over a tree answers in traversal order; a reader is owed a stable one.

    **Test steps:**

    * mock two stranded resources in directories the walk reaches in the other order
    * plan the tree
    * verify they came back sorted
    """
    mock_environment(
        mocker,
        tc_files=[],
        directories=["a", "b"],
        other_files=[
            "a/info.rehu",
            "a/info.checksum",
            "a/info.sfv",
            "b/info.rehu",
            "b/info.checksum",
            "b/info.sfv",
        ],
    )

    assert [row.rehu_path for row in plan_tc_conversion(ROOT).stranded] == [
        ROOT / "a/info.rehu",
        ROOT / "b/info.rehu",
    ]


# endregion
