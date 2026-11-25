"""Tests for finding the folders a root's layouts bucket, by the records that sit in them (#681). Pure: no disk."""

from pathlib import PurePosixPath
from typing import Any, Final
from uuid import uuid4

from pytest import mark, param
from rehuco_core import (
    TEMPORARY_BUCKET_PREFIX,
    Bucketing,
    BucketRules,
    CatalogRecord,
    Layouts,
    RecordKind,
    RecordNaming,
    RehucoRoot,
    ReplacementRule,
    bucketed_folders,
    has_bucketed_layout,
    is_bucketed_template,
    record_levels,
)

LIBRARY: Final = "{site}/{buckets}/{site_id}"
"""A store library's layout."""

COLON: Final = (ReplacementRule(": ", " - "),)
"""A replacement table turning a colon into a separator a name keeps."""


def root(layouts: Layouts) -> RehucoRoot:
    """A root with these layouts.

    :param layouts: its layouts.
    :returns: the root.
    """
    return RehucoRoot(uuid4(), "Library", "//nas/data/Library", layouts, {})


def record(path: str, record_type: str = "asset", **fields: Any) -> CatalogRecord:
    """A record as the cache has it.

    :param path: its path under the root.
    :param record_type: its type.
    :param fields: its other fields.
    :returns: the record.
    """
    return CatalogRecord(path, RecordKind.REHU, type=record_type, **fields)


def fab_item(path: str, site_id: str) -> CatalogRecord:
    """A library item's record.

    :param path: its path under the root.
    :param site_id: its store id.
    :returns: the record.
    """
    return record(path, publisher="Fab", site_ids=(("Fab", site_id),))


@mark.parametrize(
    "path, levels",
    [
        param("Fab/0/01abc/info.rehu", ("Fab", "0", "01abc"), id="a-folder-record"),
        param("Fab/0/01abc.rehu", ("Fab", "0", "01abc"), id="a-file-record"),
        param("Fab/01abc/info.tc", ("Fab", "01abc"), id="a-legacy-record"),
        param("info.rehu", (), id="the-roots-own-folder"),
    ],
)
def test_a_records_levels_end_at_its_own_entry(path: str, levels: tuple[str, ...]) -> None:
    """A folder record's entry is its folder, a file record's its stem.

    **Test steps:**

    * ask for the levels of each record
    * verify them
    """
    assert record_levels(record(path)) == levels


@mark.parametrize("item", ["Fab/01abc/info.rehu", "Fab/0/01/01abc.rehu", "fab/0/01abc/info.rehu"])
def test_a_folder_holding_a_record_at_its_place_is_bucketed(item: str) -> None:
    """Split or not, the folder before ``{buckets}`` counts once a record sits at its place in it, spelled as it is on
    the disk.

    **Test steps:**

    * find the bucketed folders of a root with one library item, unsplit, two buckets deep, and in another case
    * verify the site's folder
    """
    found = bucketed_folders([fab_item(item, "01ABC")], root({"asset": (LIBRARY,)}), ())

    assert found == (PurePosixPath(item.split("/", maxsplit=1)[0]),)


def test_a_folder_no_record_is_at_its_place_in_is_not_bucketed() -> None:
    """A folder a template's wildcards would fit is left alone: another type's, a record named otherwise, one the
    layout refuses, one no scan could read and one describing the root's own folder.

    **Test steps:**

    * find the bucketed folders of a root with a bucketed layout for assets and a plain one for tutorials, holding one
      such record of each kind
    * verify there is none
    """
    records = [
        record("Jane/Intro/info.rehu", "tutorial", title="Intro", publisher="Jane"),
        fab_item("Fab/other name/info.rehu", "01abc"),
        record("Epic/01abc/info.rehu", publisher="Epic"),
        record("Fab/02abc/info.rehu", publisher="Fab", site_ids=(("Fab", "02abc"),), error="unreadable"),
        fab_item("info.rehu", "03abc"),
    ]

    assert not bucketed_folders(records, root({"asset": (LIBRARY,), "tutorial": ("{publisher}/{title}",)}), ())


def test_a_site_id_of_another_source_names_no_place() -> None:
    """The id a layout reads is the primary source's, whose site is the record's publisher.

    **Test steps:**

    * find the bucketed folders of a root holding one record with an id on another store alone
    * verify there is none; with its own store's id beside it, its folder
    """
    layouts = root({"asset": (LIBRARY,)})

    assert not bucketed_folders(
        [record("Fab/e-1/info.rehu", publisher="Fab", site_ids=(("Epic", "e-1"),))], layouts, ()
    )
    assert bucketed_folders(
        [record("Fab/f-1/info.rehu", publisher="Fab", site_ids=(("Epic", "e-1"), ("Fab", "f-1")))], layouts, ()
    ) == (PurePosixPath("Fab"),)


def test_each_bucketed_level_of_each_template_counts_the_deepest_first() -> None:
    """A template may bucket two levels, and a type have several templates; each folder is told once, inner ones first.

    **Test steps:**

    * find the bucketed folders of a root with a two-level template, a one-level one and a plain one, two records in
      the same folders of the first and one in the second's
    * verify the folders, the deepest first
    """
    layouts = root({"*": ("{publisher}/{buckets}/{authors}/{buckets}/{title}", "ALL/{buckets}/{title}", "{title}")})
    records = [
        record("Udemy/j/Jane/Intro/info.rehu", "tutorial", title="Intro", publisher="Udemy", authors=("Jane",)),
        record("Udemy/j/Jane/b/Basics.rehu", "tutorial", title="Basics", publisher="Udemy", authors=("Jane",)),
        record("ALL/Other/info.rehu", "tutorial", title="Other", publisher="Udemy", authors=("Jane",)),
        record("Plain/info.rehu", "tutorial", title="Plain", publisher="Udemy", authors=("Jane",)),
    ]

    assert bucketed_folders(records, layouts, ()) == (
        PurePosixPath("Udemy", "j", "Jane"),
        PurePosixPath("ALL"),
        PurePosixPath("Udemy"),
    )


def test_a_root_may_bucket_its_own_folder() -> None:
    """A layout starting with ``{buckets}`` buckets the root's folder itself.

    **Test steps:**

    * find the bucketed folders of a root whose layout starts with it
    * verify the root's own folder
    """
    found = bucketed_folders(
        [record("i/Intro/info.rehu", "tutorial", title="Intro")], root({"*": ("{buckets}/{title}",)}), ()
    )

    assert found == (PurePosixPath(),)


def test_a_record_in_a_temporary_bucket_is_at_its_place() -> None:
    """A split stopped halfway is found by the records it set aside.

    **Test steps:**

    * find the bucketed folders of a root whose one record is in a temporary bucket
    * verify its folder
    """
    item = fab_item(f"Fab/{TEMPORARY_BUCKET_PREFIX}0-0a1b2c3d/0/info.rehu", "0")

    assert bucketed_folders([item], root({"asset": (LIBRARY,)}), ()) == (PurePosixPath("Fab"),)


def test_a_place_is_rendered_with_the_location_replacements() -> None:
    """A record placed by the replacements is found by them.

    **Test steps:**

    * find the bucketed folders of a root whose one record's title the replacements change
    * verify its folder with them
    """
    item = record("ALL/a/A - B/info.rehu", "tutorial", title="A: B")
    layouts = root({"*": ("ALL/{buckets}/{title}",)})

    assert bucketed_folders([item], layouts, COLON) == (PurePosixPath("ALL"),)


def test_a_cached_records_naming_is_its_fields() -> None:
    """What a layout reads of a cached record is what it reads of the record itself.

    **Test steps:**

    * name a reference pack by its cached fields
    * verify every placeholder, its type's own count among them
    """
    cached = record(
        "Poses/info.rehu",
        "reference_images",
        title="Poses",
        publisher="Fab",
        released="2024-05",
        authors=("Jane", "John"),
        advertised_count="500+",
        site_ids=(("Fab", "f-1"),),
    )

    naming = RecordNaming.of_record(cached, "Poses")

    assert (naming.main_key, naming.folder_name) == ("reference_images", "Poses")
    assert "count" in naming.placeholders
    assert naming.values == {
        "title": "Poses",
        "publisher": "Fab",
        "authors": "Jane, John",
        "year": "2024",
        "count": "500+",
        "site": "Fab",
        "site_id": "f-1",
    }


@mark.parametrize(
    "template, bucketed",
    [
        param(LIBRARY, True, id="a-bucketed-level"),
        param("{count}/{buckets}/{title}", True, id="beside-a-types-own-placeholder"),
        param("{site}/{site_id}", False, id="none"),
        param("*", False, id="keep-the-name"),
        param("{buckets/{title}", False, id="no-template"),
    ],
)
def test_a_layout_is_bucketed_when_a_template_names_buckets(template: str, bucketed: bool) -> None:
    """A root has something to rebalance when one of its templates, of any type, names ``{buckets}``.

    **Test steps:**

    * ask about each template, and about a root with it among plain ones
    * verify the answer
    """
    assert is_bucketed_template(template) is bucketed
    assert has_bucketed_layout({"*": ("{title}",), "asset": ("{title}", template)}) is bucketed


# region A split folder's layouts


@mark.parametrize(
    "folder, layouts, items, expected",
    [
        param("Fab", {"asset": ("{site}/{site_id}",)}, ["Fab/0/0abc"], Bucketing.UNGOVERNED, id="no-rule-left"),
        param("Fab", {"asset": ("{site}/{site_id}",)}, [], Bucketing.UNGOVERNED, id="no-rule-left-nor-record"),
        param("Fab", {"asset": (LIBRARY,)}, ["Fab/0/0abc"], Bucketing.GOVERNED, id="a-record-at-its-place"),
        param("fab", {"asset": (LIBRARY,)}, ["fab/0/0abc"], Bucketing.GOVERNED, id="in-another-case"),
        param("Fab", {"asset": (LIBRARY,)}, ["Fab/0/drifted"], Bucketing.GOVERNED, id="its-record-off-its-place"),
        param("Fab", {"asset": (LIBRARY,)}, ["Other/0abc"], Bucketing.GOVERNED, id="its-record-elsewhere"),
        param("Old", {"asset": (LIBRARY,)}, ["Old/0/0abc"], Bucketing.UNGOVERNED, id="another-folder-is-bucketed"),
        param("Old", {"asset": (LIBRARY,)}, ["Fab/0abc"], Bucketing.UNKNOWN, id="no-record-beneath"),
        param("Fab", {"asset": (LIBRARY,)}, [], Bucketing.UNKNOWN, id="a-root-never-scanned"),
        param("Old", {"asset": (LIBRARY,)}, ["Old.rehu"], Bucketing.UNKNOWN, id="beside-it-only"),
        param("", {"asset": ("{buckets}/{site_id}",)}, ["0/0abc"], Bucketing.GOVERNED, id="the-roots-own-folder"),
        param("", {"asset": (LIBRARY,)}, ["0/0abc"], Bucketing.UNGOVERNED, id="the-roots-own-folder-no-more"),
    ],
)
def test_a_split_folder_is_governed_where_a_records_place_leads(
    folder: str, layouts: Layouts, items: list[str], expected: Bucketing
) -> None:
    """A split folder is governed when a record of the root has its bucketed place there, wherever the record is; it is
    not when the root has no such rule, or the records beneath it have their places elsewhere; with none known beneath
    it, nothing says.

    **Test steps:**

    * ask about a folder of a root with a layout and one library item, or none
    * verify the answer
    """
    records = [fab_item(item if item.endswith(".rehu") else f"{item}/info.rehu", "0abc") for item in items]

    assert BucketRules(records, root(layouts), ()).of(PurePosixPath(folder)) is expected


@mark.parametrize("template", ["{site}/{buckets}/{site_idd}", "{site}/{buckets}", "{site/{buckets}/{site_id}"])
def test_a_layout_that_cannot_be_used_says_nothing_is_ungoverned(template: str) -> None:
    """A mistyped rule buckets nothing, and its library is not flattened for it: nothing is known until it is right.

    **Test steps:**

    * ask about a library's folder under a rule with a mistake, alone and beside one without buckets
    * verify nothing is known
    """
    items = [fab_item("Fab/0/0abc/info.rehu", "0abc")]

    for layouts in ({"asset": (template,)}, {"asset": ("{site}/{site_id}",), "tutorial": (template,)}):
        assert BucketRules(items, root(layouts), ()).of(PurePosixPath("Fab")) is Bucketing.UNKNOWN


def test_a_root_no_scan_has_read_says_nothing_is_ungoverned() -> None:
    """One record cached by an opening, astray, is no evidence about a library never scanned; with no rule left at all
    none is needed.

    **Test steps:**

    * ask about a folder with one stray record beneath, in a root with another rule and in one with none, not scanned
    * verify nothing is known in the first, and the second's is not governed
    """
    items = [fab_item("Old/0/0abc/info.rehu", "0abc")]
    old = PurePosixPath("Old")

    assert BucketRules(items, root({"asset": (LIBRARY,)}), (), scanned=False).of(old) is Bucketing.UNKNOWN
    plain = root({"asset": ("{site}/{site_id}",)})
    assert BucketRules(items, plain, (), scanned=False).of(old) is Bucketing.UNGOVERNED


def test_a_folder_inside_an_outer_levels_old_buckets_is_still_governed() -> None:
    """With only a template's outer ``{buckets}`` removed, the folders its inner one buckets are governed inside the
    outer level's buckets, and the outer folder is not.

    **Test steps:**

    * ask about both folders of a record placed by the template with both levels, the layout having the inner alone
    * verify the inner is governed, the outer not
    """
    item = record("Udemy/j/Jane/i/Intro/info.rehu", "tutorial", title="Intro", publisher="Udemy", authors=("Jane",))
    split = (PurePosixPath("Udemy"), PurePosixPath("Udemy", "j", "Jane"))
    rules = BucketRules([item], root({"*": ("{publisher}/{authors}/{buckets}/{title}",)}), (), split=split)

    assert rules.of(PurePosixPath("Udemy", "j", "Jane")) is Bucketing.GOVERNED
    assert rules.of(PurePosixPath("Udemy")) is Bucketing.UNGOVERNED


def test_a_folder_in_a_plain_folder_named_like_a_bucket_is_not_the_one_bucketed() -> None:
    """Only a split folder has buckets: ``f/Fab``, with ``f`` a folder of its own, is not ``Fab``.

    **Test steps:**

    * ask about both under a library's layout, a record beneath each
    * verify the first is not governed and the second is
    """
    items = [fab_item("f/Fab/0/0abc/info.rehu", "0abc"), fab_item("Fab/0/0abd/info.rehu", "0abd")]
    split = (PurePosixPath("f", "Fab"), PurePosixPath("Fab"))
    rules = BucketRules(items, root({"asset": (LIBRARY,)}), (), split=split)

    assert rules.of(PurePosixPath("f", "Fab")) is Bucketing.UNGOVERNED
    assert rules.of(PurePosixPath("Fab")) is Bucketing.GOVERNED


def test_records_no_scan_could_read_say_nothing() -> None:
    """A library whose records all fail to be read is not taken for one no rule buckets.

    **Test steps:**

    * ask about a folder whose one record has an error, under a layout with buckets
    * verify nothing is known
    """
    item = record("Fab/0/0abc/info.rehu", error="unreadable")

    assert BucketRules([item], root({"asset": (LIBRARY,)}), ()).of(PurePosixPath("Fab")) is Bucketing.UNKNOWN


# endregion
