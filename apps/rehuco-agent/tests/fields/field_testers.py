"""Test-only `Field` subclasses that inject fixed viewer/editor tabs.

Production requires ``viewer_tab``/``editor_tab`` on every field (the concrete surfaces live in the
assembler, not the toolkit). Tests don't care which tabs a field lands on, so each ``*Tester`` here
supplies throwaway :data:`TEST_VIEWER_TAB` / :data:`TEST_EDITOR_TAB` and otherwise forwards its
arguments unchanged -- a test constructs ``TextFieldTester("title")`` exactly as it used to construct
``TextField("title")``.
"""

from typing import Any

from rehuco_agent.fields.boolean_field import BooleanField
from rehuco_agent.fields.date_field import DateField
from rehuco_agent.fields.description_field import DescriptionField
from rehuco_agent.fields.duration_field import DurationField
from rehuco_agent.fields.field import Field, FieldsTab
from rehuco_agent.fields.file_size_field import FileSizeField
from rehuco_agent.fields.images_field import ImagesField
from rehuco_agent.fields.int_field import IntField
from rehuco_agent.fields.multiple_choice_field import MultipleChoiceField
from rehuco_agent.fields.path_field import PathField
from rehuco_agent.fields.rating_field import RatingField
from rehuco_agent.fields.text_field import TextField
from rehuco_agent.fields.text_list_field import TextListField
from rehuco_agent.fields.url_field import UrlField

TEST_VIEWER_TAB = FieldsTab("Test Viewer", ":/test/viewer.svg")
TEST_EDITOR_TAB = FieldsTab("Test Editor", ":/test/editor.svg")


class FieldTester[T](Field[T]):  # pylint: disable=abstract-method
    """The abstract `Field` base with fixed test tabs (for base-class tests)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class TextFieldTester(TextField):
    """`TextField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class UrlFieldTester(UrlField):
    """`UrlField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class TextListFieldTester(TextListField):
    """`TextListField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class BooleanFieldTester(BooleanField):
    """`BooleanField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class DateFieldTester(DateField):
    """`DateField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class DurationFieldTester(DurationField):
    """`DurationField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class FileSizeFieldTester(FileSizeField):
    """`FileSizeField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class IntFieldTester(IntField):
    """`IntField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class RatingFieldTester(RatingField):
    """`RatingField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class MultipleChoiceFieldTester(MultipleChoiceField):
    """`MultipleChoiceField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class PathFieldTester(PathField):
    """`PathField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class DescriptionFieldTester(DescriptionField):
    """`DescriptionField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)


class ImagesFieldTester(ImagesField):
    """`ImagesField` with fixed test tabs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **kwargs)
