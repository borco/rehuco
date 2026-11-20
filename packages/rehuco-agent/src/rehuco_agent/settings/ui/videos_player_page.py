"""Videos / Player settings page: where a video opens, how watching is tracked, where the maximized player goes and
how its subtitles are chosen (#316, #318, #574, #618, #692)."""

from dataclasses import dataclass
from typing import Final, override

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QRadioButton, QWidget
from rehuco_core import FFMPEG_LIBRARIES_TOOL, VLC_TOOL, ToolDescriptor

from ...documents.latest_runner import LatestRunner
from ...fields.widgets.overlay_surface import OverlayMode
from ...item_action_icons import apply_item_action_icons
from ...playback_libraries import shared_playback_libraries
from ...playback_vlc import vlc_restart_needed
from ..persistent_settings import persistent_settings
from ..tools_settings import shared_tools_settings
from ..videos_settings import (
    DEFAULT_SUBTITLE_LANGUAGES,
    FFMPEG_LIBRARIES_PLAYER,
    IN_APP_PLAYER,
    PLAYERS,
    VLC_PLAYER,
    VideosSettings,
    normalize_subtitle_languages,
    shared_videos_settings,
)
from .videos_player_page_ui import Ui_VideosPlayerPage

NEEDS_VLC_TOOLTIP: Final = "Needs VLC -- set it up in Tools."
NEEDS_LIBRARIES_TOOLTIP: Final = "Needs FFmpeg libraries -- set them up in Tools."
PLAYER_CHECK_FAILED_TEMPLATE: Final = "Checking {label} failed: {error}"

RESTART_TEXT: Final = "Takes effect at the next start."
FALLBACK_TEMPLATE: Final = (
    "This run plays with Qt's bundled FFmpeg; the libraries are tried again at the next start. {reason}"
)


@dataclass
class PlayerChoice:
    """A radio that is offered only while the tool behind it can be used, and what the page knows of that tool."""

    player: str
    """The :data:`~rehuco_agent.settings.videos_settings.PLAYERS` name the radio stands for."""

    radio: QRadioButton
    """The radio."""

    tool: ToolDescriptor
    """The external tool the choice needs."""

    tooltip: str
    """What a disabled radio says to do."""

    checker: LatestRunner
    """Asks the locator about the tool on the thread pool."""

    checked: bool = False
    """Whether the tool has been asked about."""

    reason: str | None = None
    """Why the tool cannot be used, ``None`` while it can."""

    @property
    def unusable(self) -> bool:
        """Whether the tool was asked about and cannot be used."""
        return self.checked and self.reason is not None


class VideosPlayerPage(QWidget):
    """Configure where a tutorial's videos play and how watching them is tracked.

    Four blocks:

    - **Playback** -- where a double-clicked video opens: the app's own player, or VLC once one is set up on the
      Tools page, which a link here opens when it is not. A choice already made stays selected when its VLC goes
      missing, with the reason shown; the Files sub-dock plays in the app's own player meanwhile
      ([[plugins#in-app-player]], #318).
    - **Watch progress** -- the two auto-viewed rules and the size match for renamed files, which core's
      progress write takes as parameters ([[field-schema#watch-progress]], #316).
    - **Maximized player** -- the surface the player goes over when its video is double-clicked (#574).
    - **Subtitles** (#618) -- whether a rehu's videos start with them shown, and the list of languages the subtitle
      keys visit, with a choice between that list alone and every track the video has ([[plugins#in-app-player]]).

    **The selected player reports whether its tool can actually run**, before anyone double-clicks a video. Asking
    about VLC or the FFmpeg libraries runs it, so it runs on the thread pool, each time the page is shown: a tool
    installed, updated or unmounted since is seen then.

    A sibling of `VideosProbePage` and `VideosExtensionsPage` under the "Videos" group (#692), all three over the
    one `VideosSettings`: each stages and saves only its own fields.

    Edits are staged in the widgets until :meth:`save_changes` pushes them into the shared
    `VideosSettings` and persists them.

    :param parent: optional Qt parent.
    """

    tools_requested = Signal()
    """The user followed the link to the Tools page."""

    player_checked = Signal()
    """The availability of VLC and of the FFmpeg libraries was asked of the locator and the page now shows the
    answers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_VideosPlayerPage()
        self.__ui.setupUi(self)
        self.__asked = False
        self.__pending: set[str] = set()
        self.__maximize_buttons: Final = {
            OverlayMode.DOCUMENT_OVERLAY: self.__ui.maximize_document_radio_button,
            OverlayMode.APP_WINDOW_OVERLAY: self.__ui.maximize_app_window_radio_button,
            OverlayMode.FULL_SCREEN: self.__ui.maximize_full_screen_radio_button,
        }
        self.__choices: Final = [
            PlayerChoice(VLC_PLAYER, self.__ui.vlc_player_radio_button, VLC_TOOL, NEEDS_VLC_TOOLTIP, LatestRunner(self))
        ]
        if FFMPEG_LIBRARIES_PLAYER in PLAYERS:
            self.__choices.append(
                PlayerChoice(
                    FFMPEG_LIBRARIES_PLAYER,
                    self.__ui.ffmpeg_libraries_player_radio_button,
                    FFMPEG_LIBRARIES_TOOL,
                    NEEDS_LIBRARIES_TOOLTIP,
                    LatestRunner(self),
                )
            )
        else:
            self.__ui.ffmpeg_libraries_player_radio_button.hide()
        self.__ui.subtitle_languages_editor.defaults = DEFAULT_SUBTITLE_LANGUAGES
        apply_item_action_icons(self.__ui.subtitle_languages_editor)

        for choice in self.__choices:
            choice.radio.toggled.connect(self.__on_player_toggled)
            choice.checker.read.connect(self.__on_player_checked)
        self.__ui.player_tools_link_label.linkActivated.connect(self.__on_tools_link_activated)
        shared_tools_settings().tool_changed.connect(self.__on_tool_changed)

        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether any staged choice differs from what the shared settings currently hold."""
        settings = shared_videos_settings()
        return (
            self.__staged_player() != settings.player
            or self.__ui.mark_file_viewed_check_box.isChecked() != settings.mark_file_viewed_at_end
            or self.__ui.mark_tutorial_viewed_check_box.isChecked() != settings.mark_tutorial_viewed_on_last_file
            or self.__ui.match_renamed_by_size_check_box.isChecked() != settings.match_renamed_by_size
            or self.__staged_maximize_mode() != settings.maximize_mode
            or self.__ui.subtitles_on_check_box.isChecked() != settings.subtitles_on
            or self.__ui.subtitles_all_radio_button.isChecked() != settings.subtitles_show_all
            or normalize_subtitle_languages(self.__ui.subtitle_languages_editor.values) != settings.subtitle_languages
        )

    def save_changes(self) -> None:
        """Push the staged choices into the shared settings object, persist them, and show the result.

        The page reloads itself from the saved values afterward rather than leaving them as typed:
        normalization can change the language list -- a blank or duplicated entry is dropped -- and a page still
        showing what was typed would disagree with what the subtitle keys visit.
        """
        settings = shared_videos_settings()
        settings.player = self.__staged_player()
        settings.mark_file_viewed_at_end = self.__ui.mark_file_viewed_check_box.isChecked()
        settings.mark_tutorial_viewed_on_last_file = self.__ui.mark_tutorial_viewed_check_box.isChecked()
        settings.match_renamed_by_size = self.__ui.match_renamed_by_size_check_box.isChecked()
        settings.maximize_mode = self.__staged_maximize_mode()
        settings.subtitles_on = self.__ui.subtitles_on_check_box.isChecked()
        settings.subtitles_show_all = self.__ui.subtitles_all_radio_button.isChecked()
        settings.subtitle_languages = normalize_subtitle_languages(self.__ui.subtitle_languages_editor.values)
        settings.save(persistent_settings())
        self.drop_changes()

    # pylint: disable=duplicate-code  # the three Videos pages stage and show alike
    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding every widget from the shared settings."""
        self.__show(shared_videos_settings())

    def seed_defaults(self) -> None:
        """Stage the factory values: what an unloaded `VideosSettings` holds (#342)."""
        self.__show(VideosSettings())

    @override
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  (Qt API name)
        """Ask whether VLC and the FFmpeg libraries are usable the first time the page is shown; after that the Tools
        settings say when either may have changed.

        :param event: the show event.
        """
        super().showEvent(event)
        if not self.__asked:
            self.refresh_availability()

    # pylint: enable=duplicate-code

    def refresh_availability(self) -> None:
        """Ask whether the saved VLC and FFmpeg libraries can be used, off the GUI thread; the page follows the
        answers.

        Nothing is searched for: an empty path means the best install `ToolDiscovery` recorded, and only a custom
        path is looked at, which reads its version once.
        """
        self.__asked = True
        tools = shared_tools_settings()
        self.__pending = {choice.player for choice in self.__choices}
        for choice in self.__choices:
            choice.checker.start(choice.player, lambda tool=choice.tool: tools.unusable_reason(tool))

    def __show(self, settings: VideosSettings) -> None:
        """Fill every widget from ``settings``.

        :param settings: the values to show -- the shared object's saved ones, or a fresh one's defaults.
        """
        for choice in self.__choices:
            if settings.player == choice.player:
                choice.radio.setChecked(True)
                break
        else:
            self.__ui.in_app_player_radio_button.setChecked(True)
        self.__ui.mark_file_viewed_check_box.setChecked(settings.mark_file_viewed_at_end)
        self.__ui.mark_tutorial_viewed_check_box.setChecked(settings.mark_tutorial_viewed_on_last_file)
        self.__ui.match_renamed_by_size_check_box.setChecked(settings.match_renamed_by_size)
        self.__maximize_buttons[settings.maximize_mode].setChecked(True)
        self.__ui.subtitles_on_check_box.setChecked(settings.subtitles_on)
        self.__ui.subtitles_all_radio_button.setChecked(settings.subtitles_show_all)
        self.__ui.subtitles_selected_radio_button.setChecked(not settings.subtitles_show_all)
        self.__ui.subtitle_languages_editor.values = settings.subtitle_languages
        self.__update_player_controls()

    def __staged_player(self) -> str:
        """The player currently selected in the radio buttons.

        :returns: the name of the checked radio's player; ``IN_APP_PLAYER`` when no gated one is.
        """
        return next((choice.player for choice in self.__choices if choice.radio.isChecked()), IN_APP_PLAYER)

    def __staged_maximize_mode(self) -> OverlayMode:
        """The surface a maximized player goes over, as the radio buttons show it (#574).

        :returns: the checked radio's surface; three exclusive radios in one frame always have one checked.
        """
        return next(mode for mode, button in self.__maximize_buttons.items() if button.isChecked())

    def __update_player_controls(self) -> None:
        """Offer VLC and the FFmpeg libraries only while they can be had, and say why when the staged choice cannot be
        honored, or when it waits for the next start.

        **Disabled rather than hidden**, a selected one stays enabled, and the reason sits beside it -- the Files
        sub-dock plays in the app's own player meanwhile.
        """
        for choice in self.__choices:
            choice.radio.setEnabled((choice.checked and not choice.unusable) or choice.radio.isChecked())
            choice.radio.setToolTip("" if choice.radio.isEnabled() else choice.tooltip)
        self.__ui.player_tools_link_label.setVisible(any(choice.unusable for choice in self.__choices))
        shown = next((choice for choice in self.__choices if choice.unusable and choice.radio.isChecked()), None)
        self.__ui.player_availability_label.setText((shown.reason or "") if shown is not None else "")
        self.__ui.player_availability_label.setVisible(shown is not None)
        restart = self.__restart_text()
        self.__ui.player_restart_label.setText(restart)
        self.__ui.player_restart_label.setVisible(bool(restart))

    def __restart_text(self) -> str:
        """What the staged decoder choice needs from the user: a restart, or a word about the last start's fallback.

        The libraries load before the player's code does, so a change reaches only the next start; and a build that
        could not be loaded at this start leaves Qt's own in use, whatever the page shows chosen.

        Said between the two Qt choices; VLC applies at the next video selected, unless this run already loaded another
        VLC's library, which python-vlc binds once per process (#319).

        :returns: the sentence, or an empty string when the staged choice is what this run applied.
        """
        libraries = shared_playback_libraries()
        staged = self.__staged_player()
        wanted = staged == FFMPEG_LIBRARIES_PLAYER
        if wanted and libraries.requested and libraries.fallback_reason is not None:
            return FALLBACK_TEMPLATE.format(reason=libraries.fallback_reason)
        if staged == VLC_PLAYER:
            return RESTART_TEXT if vlc_restart_needed() else ""
        return RESTART_TEXT if wanted != (libraries.loaded_from is not None) else ""

    def __on_tool_changed(self, tool_id: str) -> None:
        """Ask again when VLC's or the FFmpeg libraries' path or detection changed, if the page has asked at all.

        :param tool_id: the tool that changed.
        """
        if tool_id in (VLC_TOOL.ID, FFMPEG_LIBRARIES_TOOL.ID) and self.__asked:
            self.refresh_availability()

    def __on_player_checked(self, tag: str, result: object) -> None:
        """Take the answer of one tool's check.

        :param tag: the player the tool serves.
        :param result: the reason the tool cannot be used, ``None`` when it can, or the error the check raised.
        """
        choice = next(choice for choice in self.__choices if choice.player == tag)
        choice.checked = True
        if isinstance(result, Exception):
            choice.reason = PLAYER_CHECK_FAILED_TEMPLATE.format(label=choice.tool.LABEL, error=result)
        else:
            choice.reason = result if isinstance(result, str) else None
        self.__update_player_controls()
        self.__pending.discard(tag)
        if not self.__pending:
            self.player_checked.emit()

    def __on_player_toggled(self, checked: bool) -> None:
        """Follow the player choice.

        :param checked: whether the radio is now checked; unused, the staged state is read back.
        """
        del checked
        self.__update_player_controls()

    def __on_tools_link_activated(self, link: str) -> None:
        """Open the Tools page.

        :param link: the label's link target; unused.
        """
        del link
        self.tools_requested.emit()
