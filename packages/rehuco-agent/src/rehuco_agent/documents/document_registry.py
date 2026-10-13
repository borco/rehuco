"""One shared view-model per open document, whoever shows it ([[plugins#view-model]])."""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Final, cast

from borco_core.logging import LogScope
from PySide6.QtCore import QObject
from rehuco_core import RehuDocument, RehuFormatError, RenameCoordinator, load_tc
from rehuco_core.access import KeyRelocation, LocalKey, NodeUnreachable, ResourceKey

from ..resource_events import ResourceEvents
from ..settings.identity_settings import shared_identity_settings
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)


class DocumentRegistry(QObject):
    """Owns every open :class:`RehuDocumentModel`, one per key, and hands the same one to every holder.

    A resource shown in two places -- a Documents dock and the Documents preview (#39, #381), say -- is **one**
    view-model, so an unsaved edit in either shows in the other ([[plugins#view-model]], #375). Each
    :meth:`acquire` is a hold and each :meth:`release` drops one; the model is parented here and freed when its
    last holder lets go, so no holder's Qt parent decides when a document dies. The unsaved-changes question
    belongs to that last release (:meth:`release_discards_edits`): closing one of several views of a dirty
    document loses nothing.

    Models are held by :attr:`~RehuDocumentModel.key` ([[nodes#access-seam]]), whichever machine holds the record.
    Keys follow the model: a :meth:`~RehuDocumentModel.convert` or a completed rename moves the model's entry to its
    new key, so a later :meth:`find` of the new key reaches the same model.

    **Every held model hears every rename** ([[mounts-and-storage#out-of-band]], #376): each announced
    relocation is handed to every model (:meth:`~RehuDocumentModel.relocate`), so a record nested under a
    renamed collection folder, or a file-scoped record inside a renamed folder, follows the rename it did not
    ask for. In the other direction, what a held model says it wrote (:attr:`~RehuDocumentModel.files_changed`,
    :attr:`~RehuDocumentModel.folder_changed`) is announced app-wide through the same events.

    :param parent: optional Qt parent.
    :param rename_coordinator: handed to every model this registry builds, so a rename from the location
        editor stands the running jobs aside instead of being refused while they finish (#241) -- the
        app's one coordinator, see ``DocumentsDock``.
    :param resource_events: the app's change announcements; ``None`` builds a private one, for a registry with
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
        self.__events: Final = resource_events if resource_events is not None else ResourceEvents(parent=self)
        self.__events.moved.connect(self.__on_moved)
        self.__models: Final[dict[ResourceKey, RehuDocumentModel]] = {}
        self.__holders: Final[dict[RehuDocumentModel, int]] = {}
        self.__keys: Final[dict[RehuDocumentModel, ResourceKey | None]] = {}
        """Each held model's key as last recorded -- kept because
        :attr:`~RehuDocumentModel.key_changed` carries only the *new* key, and rekeying needs the old
        one to drop."""

    @property
    def resource_events(self) -> ResourceEvents:
        """The change announcements this registry relocates its models from and relays their writes to -- what
        every view of an acquired model listens to as well."""
        return self.__events

    def find(self, key: ResourceKey) -> RehuDocumentModel | None:
        """The model held for ``key``, or ``None`` when nobody holds one.

        :param key: the record's key, as the caller resolved it.
        :returns: the held model, if any.
        """
        return self.__models.get(key)

    def models(self) -> list[RehuDocumentModel]:
        """Every held model, in no particular order.

        :returns: the held models.
        """
        return list(self.__holders)

    def acquire(self, key: ResourceKey, *, new: bool = False, lazy: bool = False) -> RehuDocumentModel:
        """Hold the model for ``key``: the one already held, or one built for it now.

        A model already held is returned as it is -- ``new`` changes nothing then, and a real (not
        ``lazy``) acquisition of another holder's still-unread placeholder reads it
        (:meth:`RehuDocumentModel.load_pending`, a no-op on a loaded model).

        Building one **always** yields a model, never an error ([[data-model#write-integrity]]): a file that
        is missing, unparseable or refused becomes an **empty, locked** model bound to the path, whose lock
        reason names the failure.

        :param key: the key of a ``.rehu`` to load, or to create when ``new``; a ``.tc`` loads through
            :func:`rehuco_core.load_tc` instead ([[acquisition-tooling#tc-to-rehu]]), locked and read-only.
        :param new: start an empty, already-dirty document bound to ``key``
            (:meth:`RehuDocumentModel.create_new`) instead of reading it -- nothing is written until a save.
        :param lazy: build an unread placeholder (:meth:`RehuDocumentModel.create_pending`, session
            restore, #66) that its holder reads later. Never honored for ``new`` (nothing to defer) or a
            ``.tc`` (:meth:`RehuDocument.reload`, what the deferred read runs through, re-reads only a
            ``.rehu``).
        :returns: the held model; :attr:`~RehuDocumentModel.pending` tells whether it is still unread.
        :raises NodeUnreachable: for a node's record, read through the access seam once records move there (#416).
        """
        model = self.__models.get(key)
        if model is not None:
            self.__holders[model] += 1  # pylint: disable=unsupported-assignment-operation
            if not lazy:
                model.load_pending()
            return model

        if not isinstance(key, LocalKey):
            raise NodeUnreachable(key)
        path = key.path
        model = self.__build(path, new=new, lazy=lazy and not new and path.suffix.lower() != ".tc")
        model.setParent(self)
        self.__models[key] = model  # pylint: disable=unsupported-assignment-operation
        self.__holders[model] = 1  # pylint: disable=unsupported-assignment-operation
        self.__keys[model] = key  # pylint: disable=unsupported-assignment-operation
        model.key_changed.connect(self.__on_key_changed)  # type: ignore[attr-defined]
        model.files_changed.connect(self.__events.announce_changed)
        model.folder_changed.connect(self.__events.announce_folder_changed)
        model.reloaded.connect(self.__on_reloaded)
        if not new and not model.pending:
            # opening is the access verify-on-access hears of (#487); a focus of a model already held is not one, and
            # an unread placeholder is announced by the read that loads it (its reload), never before (#66)
            self.__events.announce_accessed((key,))
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
        self.__unmap(model, self.__keys.pop(model))
        model.key_changed.disconnect(self.__on_key_changed)  # type: ignore[attr-defined]
        model.files_changed.disconnect(self.__events.announce_changed)
        model.folder_changed.disconnect(self.__events.announce_folder_changed)
        model.reloaded.disconnect(self.__on_reloaded)
        model.deleteLater()

    def release_discards_edits(self, model: RehuDocumentModel) -> bool:
        """Whether releasing ``model`` now would throw away unsaved edits -- it is dirty and this is its
        last holder. While another holder still shows it, the edits live on there, so nothing is lost.

        :param model: a model returned by :meth:`acquire`.
        :returns: whether the holder should confirm before releasing.
        :raises KeyError: if ``model`` is not held here.
        """
        return model.dirty and self.__holders[model] == 1

    def note_file_signatures(self, signatures: Mapping[Path, tuple[int, int]]) -> None:
        """Tell the held models what the files they stand for look like on disk now (#487). Each model compares it with
        what it loaded, and follows or flags a difference (:meth:`RehuDocumentModel.note_file_signature`); a path
        nobody holds is ignored.

        :param signatures: each file's path on this machine, with its modification time in nanoseconds and its size.
        """
        for path, (mtime_ns, size) in signatures.items():
            model = self.__models.get(LocalKey(path))
            if model is not None:
                model.note_file_signature(mtime_ns, size)

    def __on_reloaded(self) -> None:
        """Announce the record a held model just read again as accessed, so the catalog cache is checked against it: a
        revert is the one way an out-of-band edit reaches a document that stays open (#487)."""
        key = cast(RehuDocumentModel, self.sender()).key
        if key is not None:
            self.__events.announce_accessed((key,))

    def __on_key_changed(self, key: ResourceKey | None) -> None:
        """Move the sending model's entry to its new ``key``.

        A key another held model already has is left to that model -- two models of one record are a
        conflict this registry can't resolve, only report; the moved model stays held, just unfindable.

        :param key: the model's new key.
        """
        # only a held model is connected here: acquire connects it and the last release disconnects it
        model = cast(RehuDocumentModel, self.sender())
        self.__unmap(model, self.__keys[model])
        self.__keys[model] = key  # pylint: disable=unsupported-assignment-operation
        if key is None:
            return
        other = self.__models.get(key)
        if other is not None:
            LOG.warning("%s is already open as another document; not tracking a second one under it", key)
            return
        self.__models[key] = model  # pylint: disable=unsupported-assignment-operation

    def __on_moved(self, relocation: KeyRelocation) -> None:
        """Hand a landed rename to every held model; each adopts its own new key, if the rename moved it, and
        re-keys here through :meth:`__on_key_changed`.

        :param relocation: the rename's executed plan.
        """
        for model in list(self.__holders):
            model.relocate(relocation)

    def __unmap(self, model: RehuDocumentModel, key: ResourceKey | None) -> None:
        """Drop ``key``'s entry when it maps to ``model`` (and not to another model holding it).

        :param model: the model losing its key.
        :param key: the key it was recorded under, if any.
        """
        if key is not None and self.__models.get(key) is model:
            del self.__models[key]  # pylint: disable=unsupported-delete-operation

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
