"""Videos settings page: which backend measures a duration, over which files, and how watching is tracked
(#225, #316, #521)."""

from typing import Final, override

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget
from rehuco_core import FFMPEG_TOOL, VIDEO_EXTENSIONS, FfprobeDurationProbe, MediaInfoDurationProbe

from ...documents.latest_runner import LatestRunner
from ...item_action_icons import apply_item_action_icons
from ..persistent_settings import persistent_settings
from ..tools_settings import shared_tools_settings
from ..videos_settings import VideosSettings, normalize_extensions, shared_videos_settings
from .videos_page_ui import Ui_VideosPage

AVAILABLE_TEMPLATE: Final = "{label} is ready."
"""How a usable backend reports itself -- named rather than a bare "ready", since the message has to say
*which* of the two was checked."""

CHECKING_TEXT: Final = "Checking FFmpeg…"
NEEDS_FFMPEG_TOOLTIP: Final = "Needs FFmpeg -- set it up in Tools."
CHECK_TAG: Final = "ffmpeg"
CHECK_FAILED_TEMPLATE: Final = "Checking FFmpeg failed: {error}"


class VideosPage(QWidget):
    """Configure how a tutorial's videos are measured (#224's parameters, made the user's).

    Three blocks, the first two one per parameter `rehuco_core.rehu_content_duration.content_duration` takes:

    - **Duration probe** -- which backend reads a container. *FFmpeg (external)* is offered once FFmpeg is usable,
      and where FFmpeg is lives on the Tools page ([[packaging-deployment#external-tools]], #521), which a link
      here opens. A choice already made stays selected when its tool later goes missing, and the page says why
      rather than switching ([[appendices.settings-pages#persisting-changes]]).
    - **Video extensions** -- which files a scan measures, a `StringListEditor` (#231) wearing this app's
      icons, exactly as the reference-images list on `ImagesFilesPage` is.
    - **Watch progress** -- the two auto-viewed rules and the size match for renamed files, which core's
      progress write takes as parameters ([[field-schema#watch-progress]], #316).

    **The selected backend reports whether it can actually run**, before anyone presses Compute: a scan under an
    unusable one raises rather than measuring ``0`` ([[field-schema#duration-size]]) -- so this page is where that
    is visible instead of showing up as a row that refuses to compute. Asking about FFmpeg runs it, so it runs on
    the thread pool, each time the page is shown: a tool installed, updated or unmounted since is seen then.

    Edits are staged in the widgets until :meth:`save_changes` pushes them into the shared
    `VideosSettings` and persists them; from then on that is what the next duration scan reads. Nothing
    re-measures on save -- a measurement is only ever filled by an explicit action -- so this page has no
    live-update wiring to drive.

    :param parent: optional Qt parent.
    """

    tools_requested = Signal()
    """The user followed the link to the Tools page."""

    availability_checked = Signal()
    """FFmpeg's availability was asked of the locator and the page now shows the answer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_VideosPage()
        self.__ui.setupUi(self)
        self.__asked = False
        self.__ffmpeg_checked = False
        self.__ffmpeg_reason: str | None = None
        self.__checker: Final = LatestRunner(self)
        # the probes name themselves: LABEL exists so the choice on screen tracks the registry rather
        # than a second copy of the same two names living in the .ui
        self.__ui.mediainfo_probe_radio_button.setText(MediaInfoDurationProbe.LABEL)
        self.__ui.ffprobe_probe_radio_button.setText(FfprobeDurationProbe.LABEL)
        self.__ui.extensions_editor.defaults = VIDEO_EXTENSIONS
        apply_item_action_icons(self.__ui.extensions_editor)

        self.__ui.ffprobe_probe_radio_button.toggled.connect(self.__on_probe_toggled)
        self.__ui.tools_link_label.linkActivated.connect(self.__on_tools_link_activated)
        self.__checker.read.connect(self.__on_checked)
        shared_tools_settings().tool_changed.connect(self.__on_tool_changed)

        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether any staged choice differs from what the shared settings currently hold."""
        settings = shared_videos_settings()
        return (
            self.__staged_engine() != settings.engine
            # normalized before the comparison, so a row saving would drop anyway is not yet a change
            # and auto-apply does not tear a fresh insert out from under its open cell (#53)
            or normalize_extensions(self.__ui.extensions_editor.values) != settings.video_extensions
            or self.__ui.mark_file_viewed_check_box.isChecked() != settings.mark_file_viewed_at_end
            or self.__ui.mark_tutorial_viewed_check_box.isChecked() != settings.mark_tutorial_viewed_on_last_file
            or self.__ui.match_renamed_by_size_check_box.isChecked() != settings.match_renamed_by_size
        )

    def save_changes(self) -> None:
        """Push the staged choices into the shared settings object, persist them, and show the result.

        The page reloads itself from the saved values afterwards rather than leaving them as typed:
        normalization can change the extension list -- a blank or duplicated entry is dropped, ``MP4``
        becomes ``.mp4``, and emptying it restores the shipped formats -- and a page still showing what
        was typed would disagree with what the next scan measures.
        """
        settings = shared_videos_settings()
        settings.engine = self.__staged_engine()
        settings.extensions = normalize_extensions(self.__ui.extensions_editor.values)
        settings.mark_file_viewed_at_end = self.__ui.mark_file_viewed_check_box.isChecked()
        settings.mark_tutorial_viewed_on_last_file = self.__ui.mark_tutorial_viewed_check_box.isChecked()
        settings.match_renamed_by_size = self.__ui.match_renamed_by_size_check_box.isChecked()
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding every widget from the shared settings."""
        self.__show(shared_videos_settings())

    def seed_defaults(self) -> None:
        """Stage the factory values: what an unloaded `VideosSettings` holds (#342)."""
        self.__show(VideosSettings())

    @override
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  (Qt API name)
        """Ask whether FFmpeg is usable the first time the page is shown; after that the Tools settings say when it
        may have changed.

        :param event: the show event.
        """
        super().showEvent(event)
        if not self.__asked:
            self.refresh_availability()

    def refresh_availability(self) -> None:
        """Ask whether the saved FFmpeg can be used, off the GUI thread; the page follows the answer.

        Nothing is searched for: an empty path means the best install `ToolDiscovery` recorded, and only a custom
        path is looked at, which reads its version once.
        """
        self.__asked = True
        tools = shared_tools_settings()
        path, installs = tools.path(FFMPEG_TOOL.ID), tools.detection(FFMPEG_TOOL.ID).installs
        self.__checker.start(CHECK_TAG, lambda: FfprobeDurationProbe(path, installs).unavailable_reason())

    def __show(self, settings: VideosSettings) -> None:
        """Fill every widget from ``settings``.

        :param settings: the values to show -- the shared object's saved ones, or a fresh one's defaults.
        """
        if settings.engine == FfprobeDurationProbe.NAME:
            self.__ui.ffprobe_probe_radio_button.setChecked(True)
        else:
            self.__ui.mediainfo_probe_radio_button.setChecked(True)
        self.__ui.extensions_editor.values = settings.video_extensions
        self.__ui.mark_file_viewed_check_box.setChecked(settings.mark_file_viewed_at_end)
        self.__ui.mark_tutorial_viewed_check_box.setChecked(settings.mark_tutorial_viewed_on_last_file)
        self.__ui.match_renamed_by_size_check_box.setChecked(settings.match_renamed_by_size)
        self.__update_probe_controls()

    def __staged_engine(self) -> str:
        """The backend currently selected in the radio buttons.

        Read off the one radio, the way `DescriptionsPage` reads its engine: two mutually exclusive
        radios in one parent are never both off, so the other one needs no test of its own.

        :returns: the selected probe's :attr:`~rehuco_core.DurationProbe.NAME`.
        """
        if self.__ui.ffprobe_probe_radio_button.isChecked():
            return FfprobeDurationProbe.NAME
        return MediaInfoDurationProbe.NAME

    def __update_probe_controls(self) -> None:
        """Offer the FFmpeg choice only while it can be had, point to the Tools page when it cannot, and re-check the
        status.

        The choice is **disabled rather than hidden**, and a selected one stays enabled: a backend chosen while
        FFmpeg worked is still what the next scan will use, so it is shown, with the reason, not quietly replaced.
        """
        radio = self.__ui.ffprobe_probe_radio_button
        usable = self.__ffmpeg_checked and self.__ffmpeg_reason is None
        radio.setEnabled(usable or radio.isChecked())
        radio.setToolTip("" if radio.isEnabled() else NEEDS_FFMPEG_TOOLTIP)
        self.__ui.tools_link_label.setVisible(self.__ffmpeg_checked and self.__ffmpeg_reason is not None)
        self.__show_availability()

    def __show_availability(self) -> None:
        """Report whether the staged backend can run here, in the words the probe itself gives."""
        if self.__staged_engine() == FfprobeDurationProbe.NAME:
            if not self.__ffmpeg_checked:
                self.__ui.availability_label.setText(CHECKING_TEXT)
                return
            reason, label = self.__ffmpeg_reason, FfprobeDurationProbe.LABEL
        else:
            reason, label = MediaInfoDurationProbe().unavailable_reason(), MediaInfoDurationProbe.LABEL
        self.__ui.availability_label.setText(reason if reason is not None else AVAILABLE_TEMPLATE.format(label=label))

    def __on_tool_changed(self, tool_id: str) -> None:
        """Ask again when FFmpeg's path or detection changed, if the page has asked at all.

        :param tool_id: the tool that changed.
        """
        if tool_id == FFMPEG_TOOL.ID and self.__asked:
            self.refresh_availability()

    def __on_checked(self, tag: str, result: object) -> None:
        """Take the answer of the FFmpeg check.

        :param tag: unused; this runner does one kind of work.
        :param result: the reason FFmpeg cannot be used, ``None`` when it can, or the error the check raised.
        """
        del tag
        self.__ffmpeg_checked = True
        if isinstance(result, Exception):
            self.__ffmpeg_reason = CHECK_FAILED_TEMPLATE.format(error=result)
        else:
            self.__ffmpeg_reason = result if isinstance(result, str) else None
        self.__update_probe_controls()
        self.availability_checked.emit()

    def __on_probe_toggled(self, checked: bool) -> None:
        """Follow the backend choice.

        Connected only to ``ffprobe_probe_radio_button.toggled`` -- with exactly two mutually exclusive
        radios, that alone fires once per switch either way.

        :param checked: whether the ffprobe radio is now checked; unused (the staged state is read back
            rather than inferred from which signal reported the switch).
        """
        del checked
        self.__update_probe_controls()

    def __on_tools_link_activated(self, link: str) -> None:
        """Open the Tools page.

        :param link: the label's link target; unused.
        """
        del link
        self.tools_requested.emit()
