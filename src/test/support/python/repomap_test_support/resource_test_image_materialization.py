"""Single-image runtime materialization and exact legacy-output cleanup."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_test_image_base import TestImageError
from repomap_test_support.resource_test_image_build_context import (
    _MaterializationValidationError,
    materialization_manifest_path,
)
from repomap_test_support.resource_test_image_build_steps import (
    MaterializationContainerOwner,
    recover_interrupted_runtime_materialization,
)
from repomap_test_support.resource_test_image_commands import (
    MATERIALIZATION_NETWORK_MODE,
    MATERIALIZATION_NETWORK_POLICY,
    commit_configuration,
    container_output,
    exact_image_id,
    exception_provenance,
    install_and_probe_command,
    split_tag,
)

if TYPE_CHECKING:
    from docker import DockerClient
    from repomap_test_support.resource_run import TestResourceRun


@dataclass(frozen=True, slots=True)
class RuntimeMaterializationResult:
    image_id: str
    evidence: Mapping[str, object]
    intermediate_created: tuple[str, ...] = ()
    intermediate_removed: tuple[str, ...] = ()


class RuntimeMaterializationError(TestImageError):
    """Materialization failed with private structured causal evidence."""

    def __init__(self, message: str, evidence: Mapping[str, object]) -> None:
        self.materialization_evidence = dict(evidence)
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class IntermediateCleanupResult:
    considered: tuple[str, ...]
    positive_owned: tuple[str, ...]
    removed: tuple[str, ...]
    retained_ambiguous: tuple[str, ...]


class RuntimeImageMaterializer:
    """Create one final image through an exact container/commit lifecycle."""

    _install_and_probe_command = staticmethod(install_and_probe_command)
    _commit_configuration = staticmethod(commit_configuration)
    _split_tag = staticmethod(split_tag)
    _container_output = staticmethod(container_output)
    _exact_id = staticmethod(exact_image_id)

    def __init__(
        self,
        resource_run: TestResourceRun,
        client: DockerClient,
        *,
        repo_root: Path | None = None,
    ) -> None:
        self.client = client
        self.api = DockerSdkApi(client)
        self.containers = MaterializationContainerOwner(
            resource_run, client, repo_root=repo_root
        )

    def materialize(
        self,
        *,
        base_image_id: str,
        tag: str,
        labels: Mapping[str, str],
        dependencies: Sequence[str],
        psycopg_release_version: str,
    ) -> RuntimeMaterializationResult:
        before_ids = self._image_ids()
        intermediate_created: tuple[str, ...] = ()
        command = self._install_and_probe_command(
            dependencies, psycopg_release_version
        )
        container_id = self.containers.create(
            self._exact_id(base_image_id),
            command,
        )
        image_id: str | None = None
        error: Exception | None = None
        container = self.client.containers.get(container_id)
        container.reload()
        attrs = container.attrs
        evidence: dict[str, object] = {
            "stage": "dependency-install-and-probe",
            "container_id": container_id,
            "container_name": str(attrs.get("Name") or "").removeprefix("/"),
            "configured_network_mode": self.containers.network_mode,
            "readback_network_mode": str(
                (attrs.get("HostConfig") or {}).get("NetworkMode") or ""
            ),
            "command_category": "exact-runtime-dependency-install-and-probe",
            "execution": {"exit_code": None, "stdout": "", "stderr": ""},
            "nested_exception": None,
            "cleanup_result": "not_attempted",
            "final_container_presence": "present",
        }
        try:
            container.start()
            result = container.wait(timeout=900)
            exit_code = int(result.get("StatusCode", 2))
            evidence["execution"] = {
                "exit_code": exit_code,
                "stdout": self._container_output(container, stdout=True),
                "stderr": self._container_output(container, stdout=False),
            }
            if exit_code != 0:
                raise TestImageError("managed runtime dependency installation failed")
            evidence["stage"] = "final-image-commit"
            repository, tag_value = self._split_tag(tag)
            image = container.commit(
                repository=repository,
                tag=tag_value,
                conf=self._commit_configuration(labels),
            )
            committed_image_id = image.id
            if committed_image_id is None:
                raise TestImageError("Docker Engine commit returned no image ID")
            image_id = self._exact_id(committed_image_id)
            evidence["final_image_id"] = image_id
            new_ids = self._image_ids().difference(before_ids)
            intermediate_created = tuple(sorted(new_ids.difference({image_id})))
            evidence["intermediate_created_ids"] = list(intermediate_created)
            if new_ids != {image_id}:
                raise TestImageError(
                    "managed runtime materialization produced unexpected Engine images"
                )
        except Exception as caught:
            error = caught
            evidence["nested_exception"] = self._exception_provenance(caught)
        try:
            cleanup_evidence = self.containers.cleanup(container_id)
        except TestImageError as cleanup_error:
            evidence["cleanup_result"] = "failed"
            evidence["final_container_presence"] = (
                "present"
                if self.api.inspect(ResourceKind.DOCKER_CONTAINER, container_id)
                is not None
                else "absent"
            )
            if error is not None:
                evidence["prior_nested_exception"] = evidence["nested_exception"]
            evidence["nested_exception"] = self._exception_provenance(cleanup_error)
            evidence["cleanup_failure"] = dict(
                getattr(cleanup_error, "cleanup_evidence", {})
            )
            compensation = "not_applicable"
            if image_id is not None:
                compensation = self._compensate_committed_candidate(
                    image_id=image_id,
                    tag=tag,
                    labels=labels,
                    base_image_id=base_image_id,
                    before_ids=before_ids,
                )
            evidence["final_image_compensation"] = compensation
            failure_kind = getattr(
                cleanup_error, "failure_kind", "identity_or_state_validation_refused"
            )
            if compensation == "failure_compensation_refused":
                failure_kind = "failure_compensation_refused"
            raise RuntimeMaterializationError(
                f"managed_runtime_build_cleanup_failed: {failure_kind}", evidence
            ) from cleanup_error
        evidence["cleanup_result"] = "removed"
        evidence["cleanup"] = dict(cleanup_evidence)
        evidence["final_container_presence"] = "absent"
        if error is not None:
            raise RuntimeMaterializationError(
                "managed runtime image materialization failed", evidence
            ) from error
        assert image_id is not None
        present = self._image_ids() if intermediate_created else set()
        intermediate_removed = tuple(
            item for item in intermediate_created if item not in present
        )
        evidence["stage"] = "completed"
        evidence["intermediate_created_ids"] = list(intermediate_created)
        evidence["intermediate_removed_ids"] = list(intermediate_removed)
        return RuntimeMaterializationResult(
            image_id=image_id,
            evidence=evidence,
            intermediate_created=intermediate_created,
            intermediate_removed=intermediate_removed,
        )

    def _compensate_committed_candidate(
        self,
        *,
        image_id: str,
        tag: str,
        labels: Mapping[str, str],
        base_image_id: str,
        before_ids: set[str],
    ) -> str:
        try:
            image_id = self._exact_id(image_id)
            base_image_id = self._exact_id(base_image_id)
            if image_id in before_ids:
                raise TestImageError("committed candidate predates materialization")
            image = self.client.images.get(image_id)
            observed_image_id = image.id
            if observed_image_id is None:
                raise TestImageError("committed candidate image ID is unavailable")
            if self._exact_id(observed_image_id) != image_id:
                raise TestImageError("committed candidate image ID differs")
            if tuple(sorted(str(item) for item in image.tags)) != (tag,):
                raise TestImageError("committed candidate tag differs")
            repository, _ = self._split_tag(tag)
            repo_digests = tuple(
                sorted(str(item) for item in image.attrs.get("RepoDigests") or ())
            )
            if repo_digests not in {(), (f"{repository}@{image_id}",)}:
                raise TestImageError("committed candidate RepoDigests differ")
            if str(image.attrs.get("Parent") or "") != base_image_id:
                raise TestImageError("committed candidate parent differs")
            observed_labels = dict(
                (image.attrs.get("Config") or {}).get("Labels") or {}
            )
            if observed_labels != dict(labels):
                raise TestImageError("committed candidate labels differ")
            if self.api.image_references(image_id):
                raise TestImageError("committed candidate is container-referenced")
            self.api.remove(ResourceKind.DOCKER_IMAGE, image_id)
            if self.api.inspect(ResourceKind.DOCKER_IMAGE, image_id) is not None:
                raise TestImageError("committed candidate absence was not proved")
        except Exception:
            return "failure_compensation_refused"
        return "removed_exact_candidate"

    @classmethod
    def _exception_provenance(cls, error: BaseException) -> dict[str, object]:
        return exception_provenance(error)

    def _image_ids(self) -> set[str]:
        return {
            self._exact_id(item.identity)
            for item in self.api.list_objects(ResourceKind.DOCKER_IMAGE)
        }


class RuntimeBuildIntermediateCleaner:
    """Validate one exact legacy build chain before non-force exact removal."""

    def __init__(self, client: DockerClient) -> None:
        self.client = client
        self.api = DockerSdkApi(client)

    def cleanup(
        self,
        *,
        final_image_id: str,
        candidate_ids: Sequence[str],
        expected_created_by: Sequence[str],
        expected_labels: Sequence[Mapping[str, str]],
    ) -> IntermediateCleanupResult:
        final_id = RuntimeImageMaterializer._exact_id(final_image_id)
        considered = tuple(RuntimeImageMaterializer._exact_id(x) for x in candidate_ids)
        if final_id in considered or len(set(considered)) != len(considered):
            raise TestImageError("final runtime image cannot be an intermediate")
        if len(considered) != len(expected_created_by) or len(considered) != len(
            expected_labels
        ):
            raise TestImageError("runtime-build intermediate recipe is incomplete")
        chain = self._parent_chain(final_id)
        ordered = tuple(reversed(chain[1 : len(considered) + 1]))
        if set(ordered) != set(considered):
            return IntermediateCleanupResult(considered, (), (), considered)
        ambiguous = []
        for image_id, created_by, labels in zip(
            ordered, expected_created_by, expected_labels, strict=True
        ):
            image = self.client.images.get(image_id)
            attrs = image.attrs
            history = self.client.api.history(image_id)
            if not history or history[0].get("CreatedBy") != created_by:
                ambiguous.append(image_id)
                continue
            tags = tuple(str(tag) for tag in attrs.get("RepoTags") or image.tags or ())
            digests = tuple(str(item) for item in attrs.get("RepoDigests") or ())
            observed_labels = dict((attrs.get("Config") or {}).get("Labels") or {})
            if tags or digests or observed_labels != dict(labels):
                ambiguous.append(image_id)
                continue
            if self.api.image_references(image_id):
                ambiguous.append(image_id)
        if ambiguous:
            return IntermediateCleanupResult(
                considered, tuple(x for x in ordered if x not in ambiguous), (), tuple(ambiguous)
            )
        removed = []
        for image_id in reversed(ordered):
            try:
                self.api.remove(ResourceKind.DOCKER_IMAGE, image_id)
            except Exception as error:
                raise TestImageError("managed_runtime_build_cleanup_failed") from error
            if self.api.inspect(ResourceKind.DOCKER_IMAGE, image_id) is not None:
                raise TestImageError("managed_runtime_build_cleanup_failed")
            removed.append(image_id)
        return IntermediateCleanupResult(
            considered, ordered, tuple(removed), ()
        )

    def _parent_chain(self, final_image_id: str) -> tuple[str, ...]:
        chain = []
        current = final_image_id
        while current:
            current = RuntimeImageMaterializer._exact_id(current)
            if current in chain:
                raise TestImageError("runtime-build image parent cycle")
            chain.append(current)
            image = self.client.images.get(current)
            current = str(image.attrs.get("Parent") or "")
        return tuple(chain)


MaterializationContainerOwner.__module__ = __name__
recover_interrupted_runtime_materialization.__module__ = __name__


__all__ = [
    "IntermediateCleanupResult",
    "MATERIALIZATION_NETWORK_MODE",
    "MATERIALIZATION_NETWORK_POLICY",
    "MaterializationContainerOwner",
    "RuntimeBuildIntermediateCleaner",
    "RuntimeImageMaterializer",
    "RuntimeMaterializationError",
    "RuntimeMaterializationResult",
    "_MaterializationValidationError",
    "materialization_manifest_path",
    "recover_interrupted_runtime_materialization",
]
