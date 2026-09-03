"""Tests for setup_console_logging."""

import logging
from collections.abc import Callable, Iterator

from borco_pyside.logging import DEFAULT_CONSOLE_LEVEL, setup_console_logging
from pytest import fixture
from pytest_mock import MockerFixture

type Configure = Callable[..., logging.Logger]


@fixture
def configure() -> Iterator[Configure]:
    """Provide a way to run the real ``setup_console_logging`` against a bare root logger.

    Two things make this necessary. ``basicConfig`` is a **no-op when the root logger already has
    handlers**, and pytest's own logging plugin attaches several of them -- after fixture setup, right
    around the test body -- so clearing them in a fixture is too early to help; the clear has to happen
    inside the call. And the root logger is process-wide, so whatever this leaves behind would decide
    what every later test measures: the handlers and the level are put back afterwards.

    :returns: a callable taking ``setup_console_logging``'s own arguments -- plus ``existing``, a
        handler to have already been attached when it runs -- and returning the root logger.
    """
    logger = logging.getLogger()
    handlers = list(logger.handlers)
    level = logger.level

    def run(existing: logging.Handler | None = None, **kwargs: int) -> logging.Logger:
        logger.handlers.clear()
        if existing is not None:
            logger.addHandler(existing)
        setup_console_logging(**kwargs)
        return logger

    yield run
    logger.handlers[:] = handlers
    logger.setLevel(level)


def test_setup_console_logging_configures_the_given_level(mocker: MockerFixture) -> None:
    """setup_console_logging configures the root logger with the given level.

    **Test steps:**

    * mock logging.basicConfig
    * call setup_console_logging with an explicit level
    * verify basicConfig was called once with that level
    """
    basic_config = mocker.patch("logging.basicConfig")

    setup_console_logging(level=logging.WARNING)

    basic_config.assert_called_once()
    assert basic_config.call_args.kwargs["level"] == logging.WARNING


def test_setup_console_logging_defaults_the_root_logger_to_debug(mocker: MockerFixture) -> None:
    """The root logger's floor defaults to DEBUG, because it is the floor for every other handler too.

    A record the root logger rejects reaches nothing at all, so a root at INFO would leave an in-app
    log surface with a debug filter that can never have anything to show.

    **Test steps:**

    * mock logging.basicConfig
    * call setup_console_logging with no arguments
    * verify basicConfig was called with level=DEBUG
    """
    basic_config = mocker.patch("logging.basicConfig")

    setup_console_logging()

    assert basic_config.call_args.kwargs["level"] == logging.DEBUG


def test_the_console_handler_keeps_its_own_higher_level(configure: Configure) -> None:
    """The console prints info and up even though the root logger passes debugs on.

    Two levels, so lowering the root one does not turn a terminal into a firehose.

    **Test steps:**

    * Call setup_console_logging on a root logger with no handlers.
    * Assert the root logger is at DEBUG and the installed handler at the console level.
    """
    root = configure()

    assert root.level == logging.DEBUG
    assert [handler.level for handler in root.handlers] == [DEFAULT_CONSOLE_LEVEL]


def test_the_console_level_is_settable(configure: Configure) -> None:
    """A caller can print more, or less, than the default without touching the root floor.

    **Test steps:**

    * Call setup_console_logging asking the console for warnings and up.
    * Assert the handler took that level and the root logger did not.
    """
    root = configure(console_level=logging.WARNING)

    assert root.level == logging.DEBUG
    assert [handler.level for handler in root.handlers] == [logging.WARNING]


def test_an_already_attached_handler_keeps_its_level(configure: Configure) -> None:
    """A handler already on the root logger is left alone -- its floor is not the console's.

    Levelling every handler would raise the floor of an in-app log surface attached earlier, which is
    precisely the records it exists to keep.

    **Test steps:**

    * Call setup_console_logging with a DEBUG handler already attached.
    * Assert that handler is still at DEBUG, and that it is still the only one -- ``basicConfig`` adds
      no console handler when the root logger already has one, so there is nothing to level here at all.
    """
    existing = logging.Handler(logging.DEBUG)

    root = configure(existing=existing)

    assert existing.level == logging.DEBUG
    assert root.handlers == [existing]
