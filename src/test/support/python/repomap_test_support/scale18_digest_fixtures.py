"""Deterministic fixtures and bounded observers for the SCALE18 campaign."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import threading

from repomap_kg.observations.raw import RawObservation


_DIGEST_SAMPLE_CADENCE_SECONDS = 0.05


class Scale18DigestCampaignError(ValueError):
    """Raised when a SCALE18 campaign input or measurement is invalid."""


class _DigestSampler:
    """Continuously sample RSS while one digest is being derived."""

    def __init__(
        self,
        rss_reader: Callable[[], int | None],
        clock: Callable[[], float],
        initial_rss: int,
        *,
        cadence_seconds: float = _DIGEST_SAMPLE_CADENCE_SECONDS,
    ) -> None:
        self._rss_reader = rss_reader
        self._clock = clock
        self._cadence_seconds = cadence_seconds
        self._maximum = initial_rss
        self._last_sample = clock()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self.settled = False

    def start(self) -> None:
        if self._thread is not None or self.settled:
            raise Scale18DigestCampaignError(
                "SCALE18 digest sampler state is invalid"
            )
        self._thread = threading.Thread(
            target=self._run,
            name="scale18-digest-rss-sampler",
            daemon=False,
        )
        self._thread.start()

    def observe(self, _chunk_bytes: int) -> None:
        self._sample(force=False)

    def finish(self) -> int:
        self._settle(final_sample=True)
        if self._error is not None:
            raise self._error
        return self._maximum

    def cancel(self) -> None:
        self._settle(final_sample=False)

    def _run(self) -> None:
        while not self._stop.wait(self._cadence_seconds):
            self._sample(force=True)
            if self._error is not None:
                self._stop.set()
                return

    def _sample(self, *, force: bool) -> None:
        with self._lock:
            if self._error is not None:
                return
            now = self._clock()
            if not force and now - self._last_sample < self._cadence_seconds:
                return
            try:
                rss_bytes = _read_rss(self._rss_reader)
            except BaseException as error:
                self._error = error
                return
            self._maximum = max(self._maximum, rss_bytes)
            self._last_sample = now

    def _settle(self, *, final_sample: bool) -> None:
        if self.settled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self._cadence_seconds * 2))
            if self._thread.is_alive():
                self._error = Scale18DigestCampaignError(
                    "SCALE18 digest sampler did not settle"
                )
                return
        if final_sample and self._error is None:
            self._sample(force=True)
        self.settled = True


class _ArtifactPeak:
    """Track external-sort growth on top of already prepared spool bytes."""

    def __init__(
        self,
        *,
        base_bytes: int,
        limit_bytes: int | None,
        free_space_reader: Callable[[], int] | None,
        free_space_floor_bytes: int | None,
    ) -> None:
        self._base_bytes = base_bytes
        self._limit_bytes = limit_bytes
        self._free_space_reader = free_space_reader
        self._free_space_floor_bytes = free_space_floor_bytes
        self._current_bytes = 0
        self.maximum_bytes = 0
        self.maximum_run_count = 0

    def observe(self, current_bytes: int, current_run_count: int) -> None:
        if (
            isinstance(current_bytes, bool)
            or not isinstance(current_bytes, int)
            or current_bytes < 0
            or isinstance(current_run_count, bool)
            or not isinstance(current_run_count, int)
            or current_run_count < 0
        ):
            raise Scale18DigestCampaignError(
                "SCALE18 temporary artifact sample is invalid"
            )
        growth_bytes = max(0, current_bytes - self._current_bytes)
        if self._free_space_reader is not None:
            floor_bytes = self._free_space_floor_bytes
            if floor_bytes is None:
                raise Scale18DigestCampaignError(
                    "SCALE18 free-space floor is invalid"
                )
            free_bytes = self._free_space_reader()
            if (
                isinstance(free_bytes, bool)
                or not isinstance(free_bytes, int)
                or free_bytes < 0
            ):
                raise Scale18DigestCampaignError(
                    "SCALE18 free-space sample is invalid"
                )
            if free_bytes - growth_bytes <= floor_bytes:
                raise Scale18DigestCampaignError(
                    "SCALE18 free-space floor reached"
                )
        self._current_bytes = current_bytes
        self.maximum_bytes = max(self.maximum_bytes, current_bytes)
        self.maximum_run_count = max(
            self.maximum_run_count,
            current_run_count,
        )
        if (
            self._limit_bytes is not None
            and self._base_bytes + current_bytes >= self._limit_bytes
        ):
            raise Scale18DigestCampaignError(
                "SCALE18 temporary artifact limit reached"
            )


class _PreparedSpoolAuthority:
    """Track per-family prepared spool bytes and their total."""

    def __init__(
        self,
        *,
        limit_bytes: int | None,
        free_space_reader: Callable[[], int] | None,
        free_space_floor_bytes: int | None,
    ) -> None:
        self._limit_bytes = limit_bytes
        self._free_space_reader = free_space_reader
        self._free_space_floor_bytes = free_space_floor_bytes
        self._family_bytes: dict[str, int] = {}
        self.current_bytes = 0

    def observe(self, family: str, projected_bytes: int) -> None:
        previous_bytes = self._family_bytes.get(family, 0)
        if (
            not isinstance(family, str)
            or not family
            or isinstance(projected_bytes, bool)
            or not isinstance(projected_bytes, int)
            or projected_bytes < previous_bytes
        ):
            raise Scale18DigestCampaignError(
                "SCALE18 prepared artifact sample is invalid"
            )
        growth_bytes = projected_bytes - previous_bytes
        projected_total = self.current_bytes + growth_bytes
        if (
            self._limit_bytes is not None
            and projected_total >= self._limit_bytes
        ):
            raise Scale18DigestCampaignError(
                "SCALE18 temporary artifact limit reached"
            )
        if self._free_space_reader is not None:
            floor_bytes = self._free_space_floor_bytes
            if floor_bytes is None:
                raise Scale18DigestCampaignError(
                    "SCALE18 free-space floor is invalid"
                )
            free_bytes = self._free_space_reader()
            if (
                isinstance(free_bytes, bool)
                or not isinstance(free_bytes, int)
                or free_bytes < 0
            ):
                raise Scale18DigestCampaignError(
                    "SCALE18 free-space sample is invalid"
                )
            if free_bytes - growth_bytes <= floor_bytes:
                raise Scale18DigestCampaignError(
                    "SCALE18 free-space floor reached"
                )
        self._family_bytes[family] = projected_bytes
        self.current_bytes = projected_total


def _require_free_space(
    reader: Callable[[], int] | None,
    floor_bytes: int | None,
) -> None:
    if reader is None:
        return
    if floor_bytes is None:
        raise Scale18DigestCampaignError("SCALE18 free-space floor is invalid")
    free_bytes = reader()
    if (
        isinstance(free_bytes, bool)
        or not isinstance(free_bytes, int)
        or free_bytes <= floor_bytes
    ):
        raise Scale18DigestCampaignError(
            "SCALE18 free-space floor reached"
        )


def _check_digest_deadline(
    clock: Callable[[], float],
    deadline: float,
) -> None:
    if clock() >= deadline:
        raise TimeoutError("SCALE18 digest duration limit exceeded")


def _read_rss(reader: Callable[[], int | None]) -> int:
    rss_bytes = reader()
    if (
        isinstance(rss_bytes, bool)
        or not isinstance(rss_bytes, int)
        or rss_bytes < 0
    ):
        raise Scale18DigestCampaignError(
            "SCALE18 sampled RSS is unavailable"
        )
    return rss_bytes


def _observations(profile: str, size: int) -> Iterator[RawObservation]:
    for index in range(size):
        yield _file_observation(
            index,
            payload_heavy=profile == "payload_heavy",
        )
        for proposal in range(_proposal_count(profile, index)):
            yield _import_observation(profile, index, proposal)


def _file_observation(index: int, *, payload_heavy: bool) -> RawObservation:
    path = f"fixture/module_{index:05d}.py"
    metadata: dict[str, object] = {
        "content_hash": f"{index:064x}",
        "executable": False,
        "generated": False,
        "language": "python",
        "role": "source",
    }
    if payload_heavy:
        metadata["profile_payload"] = "x" * 1_024
    return RawObservation(
        kind="file",
        source_id=path,
        path=path,
        confidence="extracted",
        extractor="scale18-public-fixture",
        extractor_version="1",
        metadata=metadata,
    )


def _proposal_count(profile: str, index: int) -> int:
    if profile == "file_raw_heavy":
        return int(index % 16 == 0)
    if profile == "canonical_node_heavy":
        return 4
    if profile == "canonical_edge_heavy":
        return 5
    if profile in {"evidence_link_heavy", "duplicate_identity_heavy"}:
        return 6
    if profile == "mixed":
        return 1 + index % 3
    return 1


def _import_observation(
    profile: str,
    index: int,
    proposal: int,
) -> RawObservation:
    path = f"fixture/module_{index:05d}.py"
    source_module = f"fixture.module_{index:05d}"
    if profile == "duplicate_identity_heavy":
        target_module = "fixture.shared_dependency"
    elif profile == "evidence_link_heavy":
        target_module = f"fixture.shared_{proposal % 2}"
    elif profile == "canonical_node_heavy":
        target_module = f"fixture.node_{index:05d}_{proposal}"
    elif profile == "canonical_edge_heavy":
        target_module = f"fixture.edge_{index:05d}_{proposal}"
    else:
        target_module = f"fixture.dependency_{(index + proposal) % 64:02d}"
    metadata: dict[str, object] = {
        "module": source_module,
        "imported_module": target_module,
        "imported_names": [target_module.rsplit(".", 1)[-1]],
        "level": 0,
        "resolution": "local",
    }
    if profile == "payload_heavy":
        metadata["profile_payload"] = "y" * 1_024
    return RawObservation(
        kind="python.import",
        source_id=f"{path}#scale18-import:{proposal}",
        path=path,
        start_line=proposal + 1,
        end_line=proposal + 1,
        name=target_module,
        confidence="extracted",
        extractor="scale18-public-fixture",
        extractor_version="1",
        metadata=metadata,
    )
