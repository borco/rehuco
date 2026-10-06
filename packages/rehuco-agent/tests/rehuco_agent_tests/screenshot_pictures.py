"""Screenshots that decode with no file on disk, for the tests of what shows them (#381)."""

from PySide6.QtGui import QImage
from pytest_mock import MockerFixture
from rehuco_agent.fields.widgets.image_source import ScreenshotRowsImageSource

FALLBACK_SIDE = 10
"""The side of a picture asked for at no particular height."""


def decodable_screenshots(mocker: MockerFixture) -> None:
    """Make every screenshot a strip shows decode as a square picture of the height it is asked for.

    The strip decodes in the background, through its source (#381), so that is where a test with no real files
    makes its screenshots loadable -- a stand-in there reaches the real loader, its cache and its timing.

    :param mocker: pytest-mock fixture.
    """

    def load(_source: ScreenshotRowsImageSource, _index: int, max_height: int | None) -> QImage:
        side = max_height or FALLBACK_SIDE
        image = QImage(side, side, QImage.Format.Format_RGB32)
        image.fill(0)
        return image

    mocker.patch.object(ScreenshotRowsImageSource, "load", load)
