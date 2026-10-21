"""One shared view-model per open document, whoever shows it ([[plugins#view-model]])."""

import logging
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Final, cast
from uuid import UUID

from borco_core.logging import LogScope
from PySide6.QtCore import QObject, Signal
from rehuco_core import RenameCoordinator, SavePayload
from rehuco_core.access import KeyRelocation, LoadedRecord, Records, ResourceKey

from ..resource_events import ResourceEvents
from ..settings.identity_settings import shared_identity_settings
from .held_files_watch import HeldFilesWatch
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)


# eight: the rename barrier, the announcements, the records, the disk watch, where pending saves are found, and the
# three maps of the held models -- each read on its own
# pylint: disable-next=too-many-instance-attributes
class DocumentRegistry(QObject):
    """Owns every open :class:`RehuDocumentModel`, one per key, and hands the same one to every holder.

    A resource shown in two places -- a Documents dock and the Documents preview (#39, #381), say -- is **one**
    view-model, so an unsaved edit in either shows in the other ([[plugins#view-model]], #375). Each
    :meth:`acquire` is a hold and each :meth:`release` drops one; the model is parented here and freed when its
    last holder lets go, so no holder's Qt parent decides when a document dies. The unsaved-changes question
    belongs to that last release (:meth:`release_discards_edits`): closing one of several views of a dirty
    document loses nothing.

    Models are held by :attr:`~RehuDocumentModel.key` ([[nodes#access-seam]]). Keys follow the model: a
    :meth:`~RehuDocumentModel.convert` or a completed rename moves the model's entry to its new key, so a later
    :meth:`find` of the new key reaches the same model.

    **Every held model hears every rename** ([[mounts-and-storage#out-of-band]], #376): each announced
    relocation is handed to every model (:meth:`~RehuDocumentModel.relocate`), so a record nested under a
    renamed collection folder, or a file-scoped record inside a renamed folder, follows the rename it did not
    ask for.

    **Every held model hears what changed on disk** (#511): when the change feed says a model's file changed -- or its
    root went stale -- the file's modification time and size are read off the GUI thread (:class:`HeldFilesWatch`) and
    handed to the model (:meth:`~RehuDocumentModel.note_file_signature`), which reloads when clean and is flagged when
    dirty. Its own save comes back the same way and changes nothing: the model already holds that signature. **A
    document under no root** has its folder watched, given ``roots``.

    :param parent: optional Qt parent.
    :param rename_coordinator: handed to every model this registry builds, so a rename from the location
        editor stands the running jobs aside instead of being refused while they finish (#241) -- the
        app's one coordinator, see ``DocumentsDock``.
    :param resource_events: the app's change announcements; ``None`` builds a private one, for a registry with
        no window around it.
    :param records: what every model's record is read and saved through ([[nodes#access-seam]], #416); ``None``
        builds one.
    :param roots: where the open ``.rehuco``'s roots are, asked whenever the held documents change -- their notifiers
        watch what is under them; ``None`` watches nothing, for a registry with no window around it.
    """

    model_acquired: Signal = Signal(object)
    """Emitted with a model this registry has just built for a first holder -- for whoever keeps state about records
    that a newly opened document must show, such as a save of it still pending (#497)."""

    def __init__(
        self,
        parent: QObject | None = None,
        rename_coordinator: RenameCoordinator | None = None,
        resource_events: ResourceEvents | None = None,
        records: Records | None = None,
        roots: Callable[[], Collection[Path]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.__rename_coordinator: Final = rename_coordinator
        self.__events: Final = resource_events if resource_events is not None else ResourceEvents(parent=self)
        self.__records: Final = records if records is not None else Records()
        self.__disk: Final = HeldFilesWatch(self.__events.changes, self.__records, rename_coordinator, roots, self)
        self.__disk.statted.connect(self.__on_statted)
        self.__disk.missing.connect(self.__on_missing)
        self.__events.moved.connect(self.__on_moved)
        self.__events.changed.connect(self.__on_files_changed)
        self.__events.root_stale.connect(self.__on_root_stale)
        self.__events.folder_changed.connect(self.__on_folder_changed)
        self.__pending_save_of: Callable[[ResourceKey], SavePayload | None] | None = None
        """Where a record's save that has not landed is found (:meth:`follow_pending_saves`)."""
        self.__models: Final[dict[ResourceKey, RehuDocumentModel]] = {}
        self.__holders: Final[dict[RehuDocumentModel, int]] = {}
        self.__keys: Final[dict[RehuDocumentModel, ResourceKey | None]] = {}
        """Each held model's key as last recorded -- kept because
        :attr:`~RehuDocumentModel.key_changed` carries only the *new* key, and rekeying needs the old
        one to drop."""

    @property
    def resource_events(self) -> ResourceEvents:
        """The change announcements this registry relocates and reloads its models from -- what every view of an
        acquired model listens to as well."""
        return self.__events

    def stop_watching(self) -> None:
        """Stop watching the folders of the documents under no root, and every read still out, before the window goes:
        nothing is delivered after."""
        self.__disk.stop()

    def watch_loose_folders(self) -> None:
        """Watch exactly the folders of the held documents under no root -- after the held documents, their keys or
        the roots changed."""
        self.__disk.follow(tuple(self.__models))

    def follow_pending_saves(self, pending_save_of: Callable[[ResourceKey], SavePayload | None]) -> None:
        """Have every document show its record's save that has not landed as the record's saved state, now and when
        opened, reverted or loaded ([[sync#unlanded-save]], #497).

        :param pending_save_of: the window's save owner's answer to *what is this record's save not landed yet*.
        """
        self.__pending_save_of = pending_save_of
        for model in list(self.__holders):
            model.follow_pending_save()

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
        """
        model = self.__models.get(key)
        if model is not None:
            self.__holders[model] += 1  # pylint: disable=unsupported-assignment-operation
            if not lazy:
                model.load_pending()
            return model

        model = self.__build(key, new=new, lazy=lazy and not new and key.path.suffix.lower() != ".tc")
        model.setParent(self)
        # a record whose save has not landed opens on that save, its saved state on this machine (#497)
        model.follow_pending_save()
        self.__models[key] = model  # pylint: disable=unsupported-assignment-operation
        self.__holders[model] = 1  # pylint: disable=unsupported-assignment-operation
        self.__keys[model] = key  # pylint: disable=unsupported-assignment-operation
        model.key_changed.connect(self.__on_key_changed)  # type: ignore[attr-defined]
        model.reloaded.connect(self.__on_reloaded)
        if not new and not model.pending:
            # opening is the access verify-on-access hears of (#487); a focus of a model already held is not one, and
            # an unread placeholder is announced by the read that loads it (its reload), never before (#66)
            self.__events.announce_accessed((key,))
        self.watch_loose_folders()
        self.model_acquired.emit(model)
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
        model.reloaded.disconnect(self.__on_reloaded)
        model.deleteLater()
        self.watch_loose_folders()

    def release_discards_edits(self, model: RehuDocumentModel) -> bool:
        """Whether releasing ``model`` now would throw away unsaved edits -- it is dirty and this is its
        last holder. While another holder still shows it, the edits live on there, so nothing is lost.

        :param model: a model returned by :meth:`acquire`.
        :returns: whether the holder should confirm before releasing.
        :raises KeyError: if ``model`` is not held here.
        """
        return model.dirty and self.__holders[model] == 1

    def __on_files_changed(self, keys: tuple[ResourceKey, ...]) -> None:
        """Read again the files of the held models a change touched -- a file itself, or a folder above it.

        :param keys: the files or folders that changed.
        """
        self.__disk.read(held for held in self.__models if any(held.is_at_or_beneath(key) for key in keys))

    def __on_folder_changed(self, folder: ResourceKey) -> None:
        """Read again the files of the held models in a folder whose listing changed -- which is also what a folder
        watch that lost events says of its whole folder, having nothing better to say (#511).

        :param folder: the folder.
        """
        self.__disk.read(held for held in self.__models if held.is_at_or_beneath(folder))

    def __on_root_stale(self, root_id: UUID) -> None:
        """Read again every held model's file: a root nothing can be trusted about may hold any of them.

        :param root_id: the root.
        """
        del root_id  # a handful of open documents is cheaper to read than to sort by root
        self.__disk.read(tuple(self.__models))

    def __on_statted(self, signatures: dict[Path, tuple[int, int]]) -> None:
        """Hand each held model what its file looks like now (GUI thread); a path nobody holds any more is ignored.

        :param signatures: each file's modification time in nanoseconds and size.
        """
        for path, (mtime_ns, size) in signatures.items():
            model = self.__models.get(ResourceKey(path))
            if model is not None:
                model.note_file_signature(mtime_ns, size)

    def __on_missing(self, missing: dict[Path, bool]) -> None:
        """Tell each held model whose file is not there that it is gone (GUI thread, #497).

        :param missing: each missing file, and whether its folder is gone too.
        """
        for path, folder_gone in missing.items():
            model = self.__models.get(ResourceKey(path))
            if model is not None:
                model.note_file_gone(folder_gone=folder_gone)

    def __on_reloaded(self) -> None:
        """Announce the record a held model just read again as accessed, so the catalog cache is checked against it:
        what a revert read -- after a change on disk, or by hand -- is what the record says now (#487)."""
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
        if key is not None and self.__models.get(key) is not None:
            LOG.warning("%s is already open as another document; not tracking a second one under it", key)
        elif key is not None:
            self.__models[key] = model  # pylint: disable=unsupported-assignment-operation
        # whatever the key became, the old one's folder may no longer need watching
        self.watch_loose_folders()

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

    def __build(self, key: ResourceKey, *, new: bool, lazy: bool) -> RehuDocumentModel:
        """Build the model for ``key`` -- see :meth:`acquire` for ``new`` and ``lazy``.

        :param key: the document's key.
        :param new: start a new, dirty document.
        :param lazy: start an unread placeholder (already narrowed by :meth:`acquire`).
        :returns: the new, parentless model.
        """
        if new:
            return RehuDocumentModel.create_new(
                key.path,
                username=shared_identity_settings().current_username,
                records=self.__records,
                rename_coordinator=self.__rename_coordinator,
                pending_save_of=self.__pending_save_for,
            )
        if lazy:
            return RehuDocumentModel.create_pending(
                key.path,
                username=shared_identity_settings().current_username,
                records=self.__records,
                rename_coordinator=self.__rename_coordinator,
                pending_save_of=self.__pending_save_for,
            )
        record = load_record(self.__records, key)
        return RehuDocumentModel(
            record.document,
            records=self.__records,
            version=record.version,
            signature=record.signature,
            rename_coordinator=self.__rename_coordinator,
            pending_save_of=self.__pending_save_for,
        )

    def __pending_save_for(self, key: ResourceKey) -> SavePayload | None:
        """A record's save that has not landed, asked of the save owner once there is one.

        :param key: the record.
        :returns: its data, or ``None``.
        """
        return None if self.__pending_save_of is None else self.__pending_save_of(key)


def load_record(records: Records, key: ResourceKey) -> LoadedRecord:
    """Read ``key``, or an empty locked stub standing in for it when it cannot be read -- the one way a record is
    read for a model, whether a holder is opening it or a model is loading it again (#381, #416).

    The record is read through ``records`` ([[nodes#access-seam]]), which routes a ``.tc`` to its own loader and draws
    the missing-vs-unparseable line once, so the holder gets a locked, never-savable stub instead of an exception
    ([[data-model#write-integrity]]). Each kind is handed the identity that matches its provenance
    (:func:`~rehuco_agent.settings.identity_settings.shared_identity_settings`, #109), read here at each read -- the
    document keeps it until it is read again, so a later identity-setting change reaches a document opened
    afterwards, or one reverted or loaded in place afterwards (#381). A ``.tc`` import files its per-user state under
    the **unknown** user, since a flag carried in from the file was not set by this install's identity; a ``.rehu``
    (whose per-user writes this UI makes) is opened under the **current** user.

    **The read is logged, under this resource's own scope** (#200); a failed read is logged by ``records``, as an
    error: there is no document -- the stub stands in for one.

    :param records: what the record is read through.
    :param key: the record (a ``.rehu``, or a legacy ``.tc``).
    :returns: the record, or a locked stub standing in for it.
    """
    settings = shared_identity_settings()
    with LogScope.open(key.path):
        record = records.load(key, username=settings.current_username, unknown_username=settings.unknown_username)
        if not record.document.load_failed:
            LOG.info("Read %s as %s", key, record.document.type or "an untyped resource")
        return record
