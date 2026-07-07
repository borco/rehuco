"""Tests for setup_console_logging."""

import logging

from borco_pyside.logging import setup_console_logging
from pytest_mock import MockerFixture


def test_setup_console_logging_configures_the_given_level(mocker: MockerFixture) -> None:
    """setup_console_logging configures the root logger with the given level.

    **Test steps:**

    * mock logging.basicConfig
    * call setup_console_logging with an explicit level
    * verify basicConfig was called once with that level
    """
    basic_config = mocker.patch("logging.basicConfig")

    setup_console_logging(level=logging.DEBUG)

    basic_config.assert_called_once()
    assert basic_config.call_args.kwargs["level"] == logging.DEBUG


def test_setup_console_logging_defaults_to_info(mocker: MockerFixture) -> None:
    """setup_console_logging defaults to INFO level when none is given.

    **Test steps:**

    * mock logging.basicConfig
    * call setup_console_logging with no arguments
    * verify basicConfig was called with level=INFO
    """
    basic_config = mocker.patch("logging.basicConfig")

    setup_console_logging()

    assert basic_config.call_args.kwargs["level"] == logging.INFO
