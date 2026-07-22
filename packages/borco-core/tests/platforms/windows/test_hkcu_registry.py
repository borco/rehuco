"""Tests for hkcu_registry's shared primitives: delete_key_tree, delete_value, get_value and
matches_verb."""

from typing import Final

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from borco_core.platforms.windows import hkcu_registry  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

from .conftest import FakeRegistry  # noqa: E402  # pylint: disable=wrong-import-position

KEY_PATH: Final = r"Software\Classes\Test.Key"
TEXT: Final = "Open in Test"
ICON: Final = r"C:\fake\test-app.exe,0"
COMMAND: Final = r'"C:\fake\test-app.exe" "%1"'


@mark.windows
def test_get_value_reads_back_a_written_value(fake_registry: FakeRegistry) -> None:
    """``get_value`` reads back exactly what ``set_value`` wrote.

    **Test steps:**

    * write a value
    * read it back
    * verify it matches
    """
    hkcu_registry.set_value(KEY_PATH, "name", "some-value")

    assert hkcu_registry.get_value(KEY_PATH, "name") == "some-value"
    assert fake_registry.values[KEY_PATH]["name"] == "some-value"


@mark.windows
def test_get_value_returns_none_for_a_missing_key(fake_registry: FakeRegistry) -> None:
    """``get_value`` returns ``None`` rather than raising when the key doesn't exist at all.

    **Test steps:**

    * read a value under a key that was never created
    * verify it returns ``None``
    """
    assert hkcu_registry.get_value(KEY_PATH, "name") is None
    assert fake_registry.values == {}


@mark.windows
def test_get_value_returns_none_for_a_missing_name(fake_registry: FakeRegistry) -> None:
    """``get_value`` returns ``None`` rather than raising when the key exists but the name doesn't.

    **Test steps:**

    * write a different value under the same key
    * read a name that was never written
    * verify it returns ``None``
    """
    hkcu_registry.set_value(KEY_PATH, "other", "some-value")

    assert hkcu_registry.get_value(KEY_PATH, "name") is None
    assert "name" not in fake_registry.values[KEY_PATH]


@mark.windows
def test_delete_value_removes_only_the_named_value(fake_registry: FakeRegistry) -> None:
    """``delete_value`` removes exactly the named value, leaving the key and its siblings intact.

    **Test steps:**

    * write two values under the same key
    * delete one of them
    * verify only that one is gone and the key with its other value survives
    """
    hkcu_registry.set_value(KEY_PATH, "mine", "some-value")
    hkcu_registry.set_value(KEY_PATH, "other", "other-value")

    hkcu_registry.delete_value(KEY_PATH, "mine")

    assert "mine" not in fake_registry.values[KEY_PATH]
    assert fake_registry.values[KEY_PATH]["other"] == "other-value"


@mark.windows
def test_delete_value_is_a_noop_when_the_key_or_value_never_existed(fake_registry: FakeRegistry) -> None:
    """``delete_value`` raises nothing when the key -- or just the value -- doesn't exist.

    **Test steps:**

    * delete a value under a key that was never created
    * create the key with a different value, then delete a name that was never written
    * verify no exception propagates either way and the existing value survives
    """
    hkcu_registry.delete_value(KEY_PATH, "name")  # key missing

    hkcu_registry.set_value(KEY_PATH, "other", "some-value")
    hkcu_registry.delete_value(KEY_PATH, "name")  # key exists, value missing

    assert fake_registry.values[KEY_PATH]["other"] == "some-value"


@mark.windows
def test_delete_value_logs_but_does_not_raise_on_other_os_errors(
    fake_registry: FakeRegistry, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """``delete_value`` doesn't conflate "value doesn't exist" with a real failure like a permission
    error: it logs a warning for anything other than ``FileNotFoundError`` but still doesn't raise --
    matching ``delete_key_tree``'s best-effort-cleanup contract.

    **Test steps:**

    * write a value so it exists
    * make the underlying ``DeleteValue`` raise ``PermissionError``
    * delete the value
    * verify no exception propagates, a warning was logged, and the value survived (the failure
      really was a failure, not a silent success)
    """
    hkcu_registry.set_value(KEY_PATH, "name", "some-value")
    mocker.patch(f"{hkcu_registry.__name__}.winreg.DeleteValue", side_effect=PermissionError("access denied"))

    hkcu_registry.delete_value(KEY_PATH, "name")  # must not raise

    assert "failed to delete" in caplog.text
    assert fake_registry.values[KEY_PATH]["name"] == "some-value"


@mark.windows
def test_delete_key_tree_is_a_noop_when_the_key_never_existed(fake_registry: FakeRegistry) -> None:
    """``delete_key_tree`` raises nothing when ``path`` doesn't exist at all.

    **Test steps:**

    * delete a key that was never created
    * verify no exception propagates
    """
    hkcu_registry.delete_key_tree(KEY_PATH)

    assert fake_registry.values == {}


@mark.windows
def test_delete_key_tree_logs_but_does_not_raise_on_other_os_errors(
    fake_registry: FakeRegistry, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """``delete_key_tree`` doesn't conflate "key doesn't exist" with a mid-tree failure like a
    permission error: it logs a warning for anything other than ``FileNotFoundError`` (so a partial
    deletion isn't a silent success) but still doesn't raise -- unregistration is best-effort cleanup
    that must not crash its caller.

    **Test steps:**

    * write a key so it exists
    * make the underlying ``DeleteKey`` raise ``PermissionError``
    * delete the key tree
    * verify no exception propagates, a warning was logged, and the key survived (the failure
      really was a failure, not a silent success)
    """
    hkcu_registry.set_value(KEY_PATH, "name", "some-value")
    mocker.patch(f"{hkcu_registry.__name__}.winreg.DeleteKey", side_effect=PermissionError("access denied"))

    hkcu_registry.delete_key_tree(KEY_PATH)  # must not raise

    assert "failed to delete" in caplog.text
    assert KEY_PATH in fake_registry.values


@mark.windows
def test_matches_verb_is_true_right_after_write_verb(fake_registry: FakeRegistry) -> None:
    """``matches_verb`` reports a match immediately after the same-shaped ``write_verb`` call.

    **Test steps:**

    * write a verb
    * check it matches the same text/icon/command
    * verify ``True``
    """
    hkcu_registry.write_verb(KEY_PATH, TEXT, ICON, COMMAND)

    assert hkcu_registry.matches_verb(KEY_PATH, TEXT, ICON, COMMAND) is True
    assert fake_registry.values[KEY_PATH][""] == TEXT


@mark.windows
def test_matches_verb_is_false_when_never_written(fake_registry: FakeRegistry) -> None:
    """``matches_verb`` reports no match when nothing was ever written at that key.

    **Test steps:**

    * check a key that was never written
    * verify ``False``
    """
    assert hkcu_registry.matches_verb(KEY_PATH, TEXT, ICON, COMMAND) is False
    assert fake_registry.values == {}


@mark.windows
def test_matches_verb_is_false_when_the_command_is_stale(fake_registry: FakeRegistry) -> None:
    """``matches_verb`` reports no match when the command points somewhere else now.

    **Test steps:**

    * write a verb, then overwrite just its command (as if the exe moved)
    * check it against the original command
    * verify ``False``
    """
    hkcu_registry.write_verb(KEY_PATH, TEXT, ICON, COMMAND)
    hkcu_registry.set_value(rf"{KEY_PATH}\command", "", r'"C:\elsewhere\test-app.exe" "%1"')

    assert hkcu_registry.matches_verb(KEY_PATH, TEXT, ICON, COMMAND) is False
    assert fake_registry.values[f"{KEY_PATH}\\command"][""] != COMMAND
