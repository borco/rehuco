"""Videos settings page: which backend measures a duration, and over which files (#225)."""

import sys
from typing import Final

from PySide6.QtWidgets import QFileDialog, QWidget
from rehuco_core import VIDEO_EXTENSIONS, FfprobeDurationProbe, MediaInfoDurationProbe

from ...string_list_editor_icons import apply_string_list_editor_icons
from ..persistent_settings import persistent_settings
from ..videos_settings import VideosSettings, normalize_extensions, shared_videos_settings
from .videos_page_ui import Ui_VideosPage

EXECUTABLE_FILTER: Final = "Executables (*.exe);;All files (*)" if sys.platform == "win32" else "All files (*)"
"""What the Browse dialog offers. Windows names the extension because a path without ``.exe`` is the
realistic mistake there; everywhere else an executable carries no extension at all."""

AVAILABLE_TEMPLATE: Final = "{label} is ready."
"""How a usable backend reports itself -- named rather than a bare "ready", since the message has to say
*which* of the two was checked."""


class VideosPage(QWidget):
    """Configure how a tutorial's videos are measured (#224's parameters, made the user's).

    Two blocks, one per parameter `rehuco_core.rehu_content_duration.content_duration` takes:

    - **Duration probe** -- which backend reads a container, plus the ``ffprobe`` executable's location,
      which is only meaningful while that backend is selected. Both are kept, so switching to MediaInfo
      and back does not lose a path that was typed ([[appendices.settings-pages#persisting-changes]]).
    - **Video extensions** -- which files a scan measures, a `StringListEditor` (#231) wearing this app's
      icons, exactly as the reference-images list on `ImagesPage` is.

    **The selected backend reports whether it can actually run**, before anyone presses Compute: an
    ``ffprobe`` path pointing at nothing is the realistic misconfiguration, and a scan under one raises
    rather than measuring ``0`` ([[field-schema#duration-size]]) -- so this page is where that is visible
    instead of showing up as a row that refuses to compute. Checked against the *staged* choice, since
    what a user wants to know while typing a path is whether the path they are typing works.

    Edits are staged in the widgets until :meth:`save_changes` pushes them into the shared
    `VideosSettings` and persists them; from then on that is what the next duration scan reads. Nothing
    re-measures on save -- a measurement is only ever filled by an explicit action -- so this page has no
    live-update wiring to drive.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_VideosPage()
        self.__ui.setupUi(self)
        # the probes name themselves: LABEL exists so the choice on screen tracks the registry rather
        # than a second copy of the same two names living in the .ui
        self.__ui.mediainfo_probe_radio_button.setText(MediaInfoDurationProbe.LABEL)
        self.__ui.ffprobe_probe_radio_button.setText(FfprobeDurationProbe.LABEL)
        self.__ui.extensions_editor.defaults = VIDEO_EXTENSIONS
        apply_string_list_editor_icons(self.__ui.extensions_editor)

        self.__ui.ffprobe_probe_radio_button.toggled.connect(self.__on_probe_toggled)
        self.__ui.ffprobe_executable_edit.textChanged.connect(self.__show_availability)
        self.__ui.browse_button.clicked.connect(self.__on_browse_clicked)

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Videos"

    def is_dirty(self) -> bool:
        """Whether any staged choice differs from what the shared settings currently hold."""
        settings = shared_videos_settings()
        return (
            self.__staged_engine() != settings.engine
            or self.__ui.ffprobe_executable_edit.text() != settings.ffprobe_executable
            or self.__ui.extensions_editor.values != settings.video_extensions
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
        settings.ffprobe_executable = self.__ui.ffprobe_executable_edit.text()
        settings.extensions = normalize_extensions(self.__ui.extensions_editor.values)
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding every widget from the shared settings."""
        settings = shared_videos_settings()
        if settings.engine == FfprobeDurationProbe.NAME:
            self.__ui.ffprobe_probe_radio_button.setChecked(True)
        else:
            self.__ui.mediainfo_probe_radio_button.setChecked(True)
        self.__ui.ffprobe_executable_edit.setText(settings.ffprobe_executable)
        self.__ui.extensions_editor.values = settings.video_extensions
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

    def __staged_probe(self) -> VideosSettings:
        """The staged choices as a settings object, so the probe is built exactly as a scan builds it.

        :returns: a throwaway `VideosSettings` holding what is on screen; the extension list is not
            copied into it, since only the probe half is asked of it.
        """
        return VideosSettings(
            engine=self.__staged_engine(),
            ffprobe_executable=self.__ui.ffprobe_executable_edit.text(),
        )

    def __update_probe_controls(self) -> None:
        """Enable the ``ffprobe`` path row only while that backend is selected, and re-check the status.

        The row is disabled rather than hidden: a path that was typed stays visible under the choice it
        belongs to, which is what says the two backends' settings are kept side by side.
        """
        ffprobe_selected = self.__staged_engine() == FfprobeDurationProbe.NAME
        self.__ui.ffprobe_executable_label.setEnabled(ffprobe_selected)
        self.__ui.ffprobe_executable_edit.setEnabled(ffprobe_selected)
        self.__ui.browse_button.setEnabled(ffprobe_selected)
        self.__show_availability()

    def __show_availability(self) -> None:
        """Report whether the staged backend can run here, in the words the probe itself gives."""
        probe = self.__staged_probe().create_probe()
        reason = probe.unavailable_reason()
        self.__ui.availability_label.setText(
            reason if reason is not None else AVAILABLE_TEMPLATE.format(label=type(probe).LABEL)
        )

    def __on_probe_toggled(self, checked: bool) -> None:
        """Follow the backend choice.

        Connected only to ``ffprobe_probe_radio_button.toggled`` -- with exactly two mutually exclusive
        radios, that alone fires once per switch either way.

        :param checked: whether the ffprobe radio is now checked; unused (the staged state is read back
            rather than inferred from which signal reported the switch).
        """
        del checked
        self.__update_probe_controls()

    def __on_browse_clicked(self) -> None:
        """Pick the ``ffprobe`` executable with a file dialog, leaving a cancelled pick untouched."""
        path, _ = QFileDialog.getOpenFileName(self, "Locate ffprobe", "", EXECUTABLE_FILTER)
        if path:
            self.__ui.ffprobe_executable_edit.setText(path)
