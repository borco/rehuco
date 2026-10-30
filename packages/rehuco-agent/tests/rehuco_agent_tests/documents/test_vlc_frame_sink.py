"""Tests for the buffer libvlc decodes into and the frames it hands on ([[appendices.vlc#memory-rendering]], #319)."""

import ctypes
import threading

from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.vlc_frame_sink import BYTES_PER_PIXEL, CHROMA, VlcFrameSink

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown


def test_the_chroma_is_32_bit_bgrx() -> None:
    """``RV32`` is what ``QImage.Format_RGB32`` reads byte for byte.

    **Test steps:**

    * check the chroma and the bytes per pixel
    """
    assert CHROMA == b"RV32"
    assert BYTES_PER_PIXEL == 4


def test_setup_allocates_and_names_the_pitch_and_lines(delete_at_teardown: DeleteAtTeardown) -> None:
    """**Test steps:**

    * set up for a 640x384 picture
    * verify the pitch is the width in bytes, the lines the height, the size kept, and a buffer address given
    """
    sink = delete_at_teardown(VlcFrameSink())

    assert sink.setup(640, 384) == (640 * 4, 384)
    assert sink.size == (640, 384)
    assert sink.lock() != 0


def test_before_setup_there_is_no_buffer_and_nothing_is_displayed(
    qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """**Test steps:**

    * lock and display an unset sink
    * verify a zero address and no frame
    """
    sink = delete_at_teardown(VlcFrameSink())
    frames: list[QImage] = []
    sink.frame_ready.connect(lambda frame, _epoch: frames.append(frame))

    assert sink.lock() == 0
    sink.display()
    qtbot.wait(20)

    assert not frames


def test_a_displayed_frame_is_a_copy_of_the_buffer_delivered_on_this_thread(
    qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """libvlc writes the buffer and displays it on a thread of its own; the frame arrives here as an image that is a
    copy, so the next write cannot change it.

    **Test steps:**

    * set up a 4x2 picture, write one colour into the buffer from another thread, and display from there
    * verify the frame arrives on this thread with that colour, and that overwriting the buffer leaves it unchanged
    """
    sink = delete_at_teardown(VlcFrameSink())
    pitch, lines = sink.setup(4, 2)
    frames: list[QImage] = []
    threads: list[str] = []

    epochs: list[int] = []

    def deliver(frame: QImage, epoch: int) -> None:
        frames.append(frame)
        epochs.append(epoch)
        threads.append(threading.current_thread().name)

    sink.frame_ready.connect(deliver)
    sink.epoch = 7

    def libvlc_thread() -> None:
        ctypes.memset(sink.lock(), 0x80, pitch * lines)
        sink.display()

    worker = threading.Thread(target=libvlc_thread, name="libvlc")
    worker.start()
    worker.join()
    qtbot.waitUntil(lambda: len(frames) == 1)
    ctypes.memset(sink.lock(), 0x00, pitch * lines)

    frame = frames[0]
    assert threads == [threading.main_thread().name]
    assert (frame.width(), frame.height()) == (4, 2)
    assert frame.pixel(1, 1) & 0xFFFFFF == 0x808080
    assert epochs == [7]


def test_cleanup_lets_the_buffer_go(delete_at_teardown: DeleteAtTeardown) -> None:
    """**Test steps:**

    * set up, then clean up
    * verify no address and no size
    """
    sink = delete_at_teardown(VlcFrameSink())
    sink.setup(8, 8)

    sink.cleanup()

    assert sink.lock() == 0
    assert sink.size == (0, 0)


def test_a_frame_due_after_the_sink_is_deleted_is_dropped() -> None:
    """libvlc may display one more frame while the engine is going; the callback must not raise into libvlc.

    **Test steps:**

    * set up, delete the sink's Qt object, and display
    * verify nothing raised
    """
    from shiboken6 import delete  # pylint: disable=import-outside-toplevel  # noqa: PLC0415

    sink = VlcFrameSink()
    sink.setup(2, 2)
    delete(sink)

    sink.display()
