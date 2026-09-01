"""Retiring one stranded legacy manifest, as a task-queue job ([[data-model#checksums]], #259).

`rehuco_core.checksum_seeding` ships :func:`~rehuco_core.remediate_legacy_manifest` as a plain callable;
this is the class that wraps one call in the queue's vocabulary, so the import wizard can hand it a
catalog's worth of resources the way it hands over conversions. The mirror of
`rehuco_core.tc_import_job`, over the state that conversion left behind before retirement existed.

**It reads no content.** One small manifest, one record, one rename -- so this job is cheap enough that a
whole library's worth of them runs while a reader watches, and there is no version of it worth pausing.

**Not safely interruptible, and it does not resume.** The one call divides no further: the record is
written atomically and the rename follows it, so a stop asked of a *running* one has no effect until it
returns on its own, and a **queued** one is cancelled outright and never starts
([[appendices.task-queue#job-responsibility]]).

**Not tracked through a** :class:`~rehuco_core.RenameCoordinator` (#241), for the reason
`rehuco_core.tc_import_job` gives: this job renames a file itself, so there is nothing stable for a
running one's ``source`` to follow.
"""

import logging
from pathlib import Path
from typing import Any, Final

from .checksum_seeding import LegacySeed, log_legacy_seed, remediate_legacy_manifest
from .constants import EXCLUDED_FILE_PATTERNS
from .resource_scoping import resource_name
from .tasks import DEFAULT_TASK_JOB_REGISTRY, JobControl, TaskJobBase
from .tc_screenshots import (
    LEGACY_SCREENSHOT_RULES,
    LegacyScreenshotRule,
    legacy_screenshot_rules_from_state,
    legacy_screenshot_rules_state,
)

LOG: Final = logging.getLogger(__name__)

LEGACY_MANIFEST_RETIRE_KIND: Final = "legacy-manifest-retire"
"""What a saved queue spells this job as ([[appendices.task-queue#lifetime]]) -- a promise once written
into a user's queue file, never casually renamed."""

STATE_PATH_KEY: Final = "path"
STATE_EXCLUDED_PATTERNS_KEY: Final = "excluded_patterns"
STATE_LEGACY_SCREENSHOT_RULES_KEY: Final = "legacy_screenshot_rules"
"""The keys this job writes itself down under, read back by this class and nothing else
([[appendices.task-queue#lifetime]])."""


class RetireLegacyManifestJob(TaskJobBase):
    """Fold one stranded manifest's claim into the record beside it and retire the file (#259).

    The remediation for what is already on disk: a resource carrying `.rehu` + `.sfv` + `.checksum`,
    converted by hand before a seed retired anything, where nothing in the files says whether the record
    came from that manifest or was baselined independently of it. What the manifest names takes the
    legacy digest with its date cleared; everything else is left alone
    (:func:`~rehuco_core.remediate_legacy_manifest`).

    **A resource with nothing to remediate is a success, not a failure.** The scan that found this one
    read a directory listing rather than the record, and the state may have been settled since -- by a
    verify that seeded and retired, or by somebody moving the file. Nothing was written; that is the
    honest outcome, and a failed row would send Retry at work already done.

    :param rehu_path: the resource's ``.rehu`` file, or ``None`` for a job about to be handed a saved
        state.
    :param legacy_screenshot_rules: the naming rules a ``.tc``'s screenshots are recognized by (#53),
        resolved by the caller alongside ``excluded_patterns``.
    :param excluded_patterns: the filename globs the content walk leaves out (#226), resolved by the
        caller -- core never reads a setting. Only content is seeded, so this decides which of the
        manifest's lines never become entries.
    :param label: how the job is named to a reader, or ``None`` for one derived from the path.
    """

    kind = LEGACY_MANIFEST_RETIRE_KIND
    safely_interruptible = False

    def __init__(
        self,
        rehu_path: Path | None = None,
        *,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        legacy_screenshot_rules: tuple[LegacyScreenshotRule, ...] = LEGACY_SCREENSHOT_RULES,
        label: str | None = None,
    ) -> None:
        super().__init__()
        self.source = rehu_path
        self.excluded_patterns = excluded_patterns
        self.legacy_screenshot_rules = legacy_screenshot_rules
        self.label = label if label is not None else self.__derived_label()
        self.__seed: LegacySeed | None = None

    @property
    def seed(self) -> LegacySeed | None:
        """What the last completed run absorbed and retired, or ``None`` before one has finished -- or
        when it found nothing to do.

        Held for the surface that enqueued the job, the same discipline
        :attr:`~rehuco_core.ChecksumJob.report` is under: the engine carries progress and an outcome,
        deliberately not a payload ([[appendices.task-queue#job-responsibility]]).
        """
        return self.__seed

    def validate(self) -> str | None:
        """Say whether this remediation can still start -- a stat, not a walk.

        :returns: ``None`` when the resource is there, else what is wrong with it.
        """
        path = self.source
        if path is None:
            return "This task has no resource."
        if not path.exists():
            return f"The resource no longer exists: {path}"
        return None

    def reset(self) -> None:
        """Drop the last run's result along with the stop request, so a retry reports its own run."""
        super().reset()
        self.__seed = None

    def run(self, control: JobControl) -> None:
        """Merge the manifest into the record and rename it aside, reporting start and finish.

        One call, no content read, so there is nothing finer than *not started* / *done* for
        :meth:`~rehuco_core.tasks.JobControl.report` to say -- which is why this job declares no
        :attr:`~rehuco_core.tasks.TaskJob.progress_unit` (#248).

        :param control: the engine's face to this job.
        :raises ContentUnreachableError: the resource's directory would not list (#245).
        :raises ChecksumRecordError: a record this build cannot read at all.
        :raises OSError: the record could not be read or re-written.
        """
        control.report(0, 1)
        path = self.resource_path()
        seed = remediate_legacy_manifest(
            path,
            excluded_patterns=self.excluded_patterns,
            legacy_screenshot_rules=self.legacy_screenshot_rules,
        )
        self.__seed = seed
        control.report(1, 1)
        if seed is None:
            LOG.info("%s had no stranded manifest to retire.", path)
            return
        count = len(seed.entries)
        LOG.info("Merged %d claim%s from %s into the record.", count, "" if count == 1 else "s", seed.manifest.name)
        log_legacy_seed(seed)

    def resource_path(self) -> Path:
        """This job's ``.rehu`` file, refusing a job that has none.

        :returns: the ``.rehu`` path.
        :raises ValueError: the job was built without a path and never given a state.
        """
        path = self.source
        if path is None:
            raise ValueError("A manifest retirement job has no resource to work on.")
        return path

    def capture_state(self) -> dict[str, Any]:
        """Hand over what this job needs to be itself again in a later run.

        :returns: JSON primitives only -- the path as text, and the exclusion set the enqueuer resolved.
        """
        path = self.source
        return {
            STATE_PATH_KEY: str(path) if path is not None else "",
            STATE_EXCLUDED_PATTERNS_KEY: list(self.excluded_patterns),
            STATE_LEGACY_SCREENSHOT_RULES_KEY: legacy_screenshot_rules_state(self.legacy_screenshot_rules),
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the job that captured ``state``.

        Read defensively, matching :meth:`~rehuco_core.TcImportJob.restore_state`'s discipline: a missing
        or malformed path raises, and the registry logs and drops the item.

        :param state: whatever this class's own :meth:`capture_state` wrote.
        :raises ValueError: the state does not describe a runnable job.
        """
        path = state.get(STATE_PATH_KEY)
        if not isinstance(path, str) or not path:
            raise ValueError("A saved manifest retirement task names no resource.")
        excluded = state.get(STATE_EXCLUDED_PATTERNS_KEY)
        self.source = Path(path)
        if isinstance(excluded, list) and all(isinstance(pattern, str) for pattern in excluded):
            self.excluded_patterns = tuple(excluded)
        rules = legacy_screenshot_rules_from_state(state.get(STATE_LEGACY_SCREENSHOT_RULES_KEY))
        if rules is not None:
            self.legacy_screenshot_rules = rules
        self.label = self.__derived_label()

    def __derived_label(self) -> str:
        """This job's own name for itself, e.g. ``"Retire legacy manifest - Sculpting Series"``.

        A fallback rather than the usual answer: a restored item's saved label is used in preference
        ([[appendices.task-queue#lifetime]]), so a row comes back reading exactly as it was written.
        """
        path = self.source
        if path is None:
            return "Retire legacy manifest"
        return f"Retire legacy manifest - {resource_name(path)}"


DEFAULT_TASK_JOB_REGISTRY.register(LEGACY_MANIFEST_RETIRE_KIND, RetireLegacyManifestJob)
