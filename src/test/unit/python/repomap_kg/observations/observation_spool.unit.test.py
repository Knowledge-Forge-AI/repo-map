import stat
import unittest

from repomap_kg.observations.raw import RawObservation
from repomap_kg.observations.spool import ObservationSpool


def _observation(source_id: str, ordinal: int) -> RawObservation:
    return RawObservation(
        kind="file",
        source_id=source_id,
        path=f"file-{ordinal}.txt",
        confidence="extracted",
        extractor="test",
        extractor_version="1",
        metadata={"ordinal": ordinal},
    )


class ObservationSpoolUnitTests(unittest.TestCase):
    def test_replays_deterministic_observations_and_cleans_up(self):
        expected = tuple(_observation(f"source-{index}", index) for index in range(3))

        with ObservationSpool.from_observations(expected) as spool:
            path = spool.path
            self.assertEqual(len(spool), len(expected))
            self.assertEqual(tuple(spool), expected)
            self.assertEqual(tuple(spool), expected)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), stat.S_IRUSR | stat.S_IWUSR)

        self.assertFalse(path.exists())

    def test_closed_spool_rejects_replay(self):
        spool = ObservationSpool.from_observations((_observation("source", 0),))
        spool.close()
        spool.close()

        with self.assertRaisesRegex(RuntimeError, "spool is closed"):
            tuple(spool)


if __name__ == "__main__":
    unittest.main()
