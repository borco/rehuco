"""One shared view-model per open document, whoever shows it ([[plugins#view-model]])."""

import logging
from pathlib import Path
from typing import Final, cast

from borco_core.logging import LogScope
from PySide6.QtCore import QObject
from rehuco_core import RehuDocument, RehuFormatError, Relocation, RenameCoordinator, load_tc

from ..resource_events import ResourceEvents
from ..settings.identity_settings import shared_identity_settings
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)


class DocumentRegistry(QObject):
    """Owns every open :class:`RehuDocumentModel`, one per path, and hands the same one to every holder.

    A resource shown in two places -- a Documents dock and the Documents preview (#39, #381), say -- is **one**
    view-model, so an unsaved edit in either shows in the other ([[plugins#view-model]], #375). Each
    :meth:`acquire` is a hold and each :meth:`release` drops one; the model is parented here and freed when its
    last holder lets go, so no holder's Qt parent decides when a document dies. The unsaved-changes question
    belongs to that last release (:meth:`release_discards_edits`): closing one of several views of a dirty
    document loses nothing.

    Keys follow the model: a :meth:`~RehuDocumentModel.convert` or a completed rename moves the model's
    entry to its new path, so a later :meth:`find` of the new path reaches the same model.

    **Every held model hears every rename** ([[mounts-and-storage#out-of-band]], #376): each announced
    relocation is handed to every model (:meth:`~RehuDocumentModel.relocate`), so a record nested under a
    renamed collection folder, or a file-scoped record inside a renamed folder, follows the rename it did not
    ask for. In the other direction, what a held model says it wrote (:attr:`~RehuDocumentModel.files_changed`,
    :attr:`~RehuDocumentModel.folder_changed`) is announced app-wide through the same events.

    :param parent: optional Qt parent.
    :param rename_coordinator: handed to every model this registry builds, so a rename from the location
        editor stands the running jobs aside instead of being refused while they finish (#241) -- the
        app's one coordinator, see ``DocumentsDock``.
    :param resource_events: the app's file announcements; ``None`` builds a private one, for a registry with
        no window around it.
    """

    def __init__(
        self,
        parent: QObject | None = None,
        rename_coordinator: RenameCoordinator | None = None,
        resource_events: ResourceEvents | None = None,
    ) -> None:
        super().__init__(parent)
        self.__rename_coordinator: Final = rename_coordinator
        self.__events: Final = resource_events if resource_events is not None else ResourceEvents(self)
        self.__events.moved.connect(self.__on_moved)
        self.__models: Final[dict[Path, RehuDocumentModel]] = {}
        self.__holders: Final[dict[RehuDocumentModel, int]] = {}
        self.__paths: Final[dict[RehuDocumentModel, Path | None]] = {}
        """Each held model's key as last recorded -- kept because
        :attr:`~RehuDocumentModel.path_changed` carries only the *new* path, and rekeying needs the old
        one to drop."""

    @property
    def resource_events(self) -> ResourceEvents:
        """The file announcements this registry relocates its models from and relays their writes to -- what
        every view of an acquired model listens to as well."""
        return self.__events

    def find(self, path: Path) -> RehuDocumentModel | None:
        """The model held for ``path``, or ``None`` when nobody holds one.

        :param path: the absolute path to look up, as the caller resolved it.
        :returns: the held model, if any.
        """
        return self.__models.get(path)

    def models(self) -> list[RehuDocumentModel]:
        """Every held model, in no particular order.

        :returns: the held models.
        """
        return list(self.__holders)

    def acquire(self, path: Path, *, new: bool = False, lazy: bool = False) -> RehuDocumentModel:
        """Hold the model for ``path``: the one already held, or one built for it now.

        A model already held is returned as it is -- ``new`` changes nothing then, and a real (not
        ``lazy``) acquisition of another holder's still-unread placeholder reads it
        (:meth:`RehuDocumentModel.load_pending`, a no-op on a loaded model).

        Building one **always** yields a model, never an error ([[data-model#write-integrity]]): a file that
        is missing, unparseable or refused becomes an **empty, locked** model bound to the path, whose lock
        reason names the failure.

        :param path: absolute filesystem path of a ``.rehu`` to load, or to create when ``new``; a ``.tc``
            loads through :func:`rehuco_core.load_tc` instead ([[acquisition-tooling#tc-to-rehu]]), locked
            and read-only.
        :param new: start an empty, already-dirty document bound to ``path``
            (:meth:`RehuDocumentModel.create_new`) instead of reading it -- nothing is written until a save.
        :param lazy: build an unread placeholder (:meth:`RehuDocumentModel.create_pending`, session
            restore, #66) that its holder reads later. Never honored for ``new`` (nothing to defer) or a
            ``.tc`` (:meth:`RehuDocument.reload`, what the deferred read runs through, re-reads only a
            ``.rehu``).
        :returns: the held model; :attr:`~RehuDocumentModel.pending` tells whether it is still unread.
        """
        model = self.__models.get(path)
        if model is not None:
            self.__holders[model] += 1  # pylint: disable=unsupported-assignment-operation
            if not lazy:
                model.load_pending()
            return model

        model = self.__build(path, new=new, lazy=lazy and not new and path.suffix.lower() != ".tc")
        model.setParent(self)
        self.__models[path] = model  # pylint: disable=unsupported-assignment-operation
        self.__holders[model] = 1  # pylint: disable=unsupported-assignment-operation
        self.__paths[model] = path  # pylint: disable=unsupported-assignment-operation
        model.path_changed.connect(self.__on_path_changed)  # type: ignore[attr-defined]
        model.files_changed.connect(self.__events.announce_changed)
        model.folder_changed.connect(self.__events.announce_folder_changed)
        return model

    def release(self, model: RehuDocumentModel) -> None:
        """Drop one hold on ``model``, freeing it when that was the last.

        Never asks anything: a holder that may be discarding edits asks :meth:`release_discards_edits`
        first and settles it with the user before releasing.

        :param model: a model returned by :meth:`acquire`.
        :raises KeyError: if ``model`` is not held here.
        """
        holders = self.__holders[model] - 1
        if holders:
            self.__holders[model] = holders  # pylint: disable=unsupported-assignment-operation
            return
        del self.__holders[model]  # pylint: disable=unsupported-delete-operation
        self.__unmap(model, self.__paths.pop(model))
        model.path_changed.disconnect(self.__on_path_changed)  # type: ignore[attr-defined]
        model.files_changed.disconnect(self.__events.announce_changed)
        model.folder_changed.disconnect(self.__events.announce_folder_changed)
        model.deleteLater()

    def release_discards_edits(self, model: RehuDocumentModel) -> bool:
        """Whether releasing ``model`` now would throw away unsaved edits -- it is dirty and this is its
        last holder. While another holder still shows it, the edits live on there, so nothing is lost.

        :param model: a model returned by :meth:`acquire`.
        :returns: whether the holder should confirm before releasing.
        :raises KeyError: if ``model`` is not held here.
        """
        return model.dirty and self.__holders[model] == 1

    def __on_path_changed(self, path: Path | None) -> None:
        """Move the sending model's key to its new ``path``.

        A path another held model already has is left to that model -- two models of one file are a
        conflict this registry can't resolve, only report; the moved model stays held, just unfindable.

        :param path: the model's new path.
        """
        # only a held model is connected here: acquire connects it and the last release disconnects it
        model = cast(RehuDocumentModel, self.sender())
        self.__unmap(model, self.__paths[model])
        self.__paths[model] = path  # pylint: disable=unsupported-assignment-operation
        if path is None:
            return
        other = self.__models.get(path)
        if other is not None:
            LOG.warning("%s is already open as another document; not tracking a second one under it", path)
            return
        self.__models[path] = model  # pylint: disable=unsupported-assignment-operation

    def __on_moved(self, relocation: Relocation) -> None:
        """Hand a landed rename to every held model; each adopts its own new path, if the rename moved it, and
        re-keys here through :meth:`__on_path_changed`.

        :param relocation: the rename's executed plan.
        """
        for model in list(self.__holders):
            model.relocate(relocation)

    def __unmap(self, model: RehuDocumentModel, path: Path | None) -> None:
        """Drop ``path``'s key when it maps to ``model`` (and not to another model holding it).

        :param model: the model losing its key.
        :param path: the key it was recorded under, if any.
        """
        if path is not None and self.__models.get(path) is model:
            del self.__models[path]  # pylint: disable=unsupported-delete-operation

    def __build(self, path: Path, *, new: bool, lazy: bool) -> RehuDocumentModel:
        """Build the model for ``path`` -- see :meth:`acquire` for ``new`` and ``lazy``.

        :param path: the document's path.
        :param new: start a new, dirty document.
        :param lazy: start an unread placeholder (already narrowed by :meth:`acquire`).
        :returns: the new, parentless model.
        """
        if new:
            return RehuDocumentModel.create_new(
                path,
                username=shared_identity_settings().current_username,
                rename_coordinator=self.__rename_coordinator,
            )
        if lazy:
            return RehuDocumentModel.create_pending(
                path,
                username=shared_identity_settings().current_username,
                rename_coordinator=self.__rename_coordinator,
            )
        return RehuDocumentModel(load_or_locked(path), rename_coordinator=self.__rename_coordinator)


def load_or_locked(path: Path) -> RehuDocument:
    """Load ``path``, or an empty locked stub bound to it when the file cannot be read -- the one way a
    document is read from a file, whether a holder is opening it or a model is loading it again (#381).

    Routes a ``.tc`` through :func:`rehuco_core.load_tc` and everything else through
    :meth:`RehuDocument.load`, but funnels *both* loaders' failures through the one seam that draws
    the missing-vs-unparseable line (:meth:`RehuDocument.locked_stub_for_error`) -- so the holder gets
    a locked, never-savable stub instead of an exception ([[data-model#write-integrity]]). Each branch
    is handed the identity that matches its provenance
    (:func:`~rehuco_agent.settings.identity_settings.shared_identity_settings`, #109), read here at
    each read -- the document keeps it until it is read again, so a later identity-setting change
    reaches a document opened afterwards, or one reverted or loaded in place afterwards, which reads its
    file through here like any open (#381). A ``.tc`` import files its per-user state under the
    **unknown** user, since a flag carried in from the file was not set by this install's identity; a
    ``.rehu`` (whose per-user writes this UI makes) is opened under the **current** user. A locked stub
    adopts whichever name its branch would have used, so a hand-fix-and-revert retries under the same
    identity the open was asked for.

    **The read is logged, under this resource's own scope** (#200): this is the one funnel both
    loaders and both failure kinds pass through, so it is the one place that can say *"this file was
    read"* or *"this file could not be"* once rather than per branch. The failure is an **error**, not
    a warning: it is not the shape of the document that is in question, it is that there is no
    document -- the stub stands in for one.

    :param path: the file to load (a ``.rehu``, or a legacy ``.tc``).
    :returns: the loaded document, or a locked stub bound to ``path``.
    """
    settings = shared_identity_settings()
    is_tc = path.suffix.lower() == ".tc"
    username = settings.unknown_username if is_tc else settings.current_username
    with LogScope.open(path):
        try:
            document = load_tc(path, username=username) if is_tc else RehuDocument.load(path, username=username)
        except (OSError, RehuFormatError) as error:
            LOG.error("Could not read %s: %s", path, error)
            return RehuDocument.locked_stub_for_error(path, error, username=username)
        LOG.info("Read %s as %s", path, document.type or "an untyped resource")
        return document
