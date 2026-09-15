import unittest

from repomap_kg.graph.readback.host_mutators import (
    filter_host_mutator_records,
    format_host_mutator_summary_table,
    format_host_mutator_table,
    host_mutator_records_from_observations,
    host_mutator_summaries_to_jsonable,
    host_mutators_to_jsonable,
    summarize_host_mutator_records,
)
from repomap_kg.observations.raw import RawObservation


class HostMutatorUnitTests(unittest.TestCase):
    def test_host_mutator_records_select_shell_host_mutation_observations(self):
        observations = [
            RawObservation(
                kind="shell.command",
                source_id="scripts/maintain.sh#call:brew-install",
                path="scripts/maintain.sh",
                start_line=2,
                end_line=2,
                name="brew install",
                target="tool:brew",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
            ),
            host_mutation_observation(
                source_id="scripts/maintain.sh#host-mutation:3:service",
                path="scripts/maintain.sh",
                line=3,
                name="launchctl bootout",
                target="host:service-management",
                category="service-management",
                tool="launchctl",
                privileged=True,
                reason="launchctl bootout",
                argv=["sudo", "launchctl", "bootout", "system/example"],
                effective_argv=["launchctl", "bootout", "system/example"],
            ),
            host_mutation_observation(
                source_id="scripts/maintain.sh#host-mutation:2:package",
                path="scripts/maintain.sh",
                line=2,
                name="brew install",
                target="host:package-management",
                category="package-management",
                tool="brew",
                privileged=False,
                reason="brew install",
                argv=["brew", "install", "postgresql"],
                effective_argv=["brew", "install", "postgresql"],
            ),
        ]

        records = host_mutator_records_from_observations(observations)

        self.assertEqual([record.name for record in records], [
            "brew install",
            "launchctl bootout",
        ])
        self.assertEqual(records[0].path, "scripts/maintain.sh")
        self.assertEqual(records[0].line, 2)
        self.assertEqual(records[0].category, "package-management")
        self.assertEqual(records[0].target, "host:package-management")
        self.assertEqual(records[1].effective_argv, (
            "launchctl",
            "bootout",
            "system/example",
        ))
        self.assertTrue(records[1].privileged)

    def test_filter_host_mutator_records_by_category_and_tool(self):
        records = host_mutator_records_from_observations(
            [
                host_mutation_observation(
                    source_id="scripts/maintain.sh#host-mutation:2:package",
                    path="scripts/maintain.sh",
                    line=2,
                    name="brew install",
                    target="host:package-management",
                    category="package-management",
                    tool="brew",
                    privileged=False,
                    reason="brew install",
                    argv=["brew", "install", "postgresql"],
                    effective_argv=["brew", "install", "postgresql"],
                ),
                host_mutation_observation(
                    source_id="scripts/maintain.sh#host-mutation:3:service",
                    path="scripts/maintain.sh",
                    line=3,
                    name="launchctl bootout",
                    target="host:service-management",
                    category="service-management",
                    tool="launchctl",
                    privileged=True,
                    reason="launchctl bootout",
                    argv=["sudo", "launchctl", "bootout", "system/example"],
                    effective_argv=["launchctl", "bootout", "system/example"],
                ),
            ]
        )

        filtered = filter_host_mutator_records(
            records,
            category="service-management",
            tool="launchctl",
        )

        self.assertEqual([record.name for record in filtered], ["launchctl bootout"])
        self.assertEqual(
            filter_host_mutator_records(records, category="filesystem-mutation"),
            (),
        )

    def test_format_host_mutator_table_uses_stable_columns(self):
        records = host_mutator_records_from_observations(
            [
                host_mutation_observation(
                    source_id="scripts/maintain.sh#host-mutation:2:package",
                    path="scripts/maintain.sh",
                    line=2,
                    name="brew install",
                    target="host:package-management",
                    category="package-management",
                    tool="brew",
                    privileged=False,
                    reason="brew install",
                    argv=["brew", "install", "postgresql"],
                    effective_argv=["brew", "install", "postgresql"],
                )
            ]
        )

        table = format_host_mutator_table(records)

        self.assertEqual(
            table,
            "\n".join(
                [
                    "path                 line  category            tool  privileged  name",
                    "scripts/maintain.sh  2     package-management  brew  false       brew install",
                ]
            ),
        )

    def test_host_mutators_to_jsonable_preserves_argv_details(self):
        records = host_mutator_records_from_observations(
            [
                host_mutation_observation(
                    source_id="scripts/maintain.sh#host-mutation:3:service",
                    path="scripts/maintain.sh",
                    line=3,
                    name="launchctl bootout",
                    target="host:service-management",
                    category="service-management",
                    tool="launchctl",
                    privileged=True,
                    reason="launchctl bootout",
                    argv=["sudo", "launchctl", "bootout", "system/example"],
                    effective_argv=["launchctl", "bootout", "system/example"],
                )
            ]
        )

        self.assertEqual(
            host_mutators_to_jsonable(records),
            [
                {
                    "argv": ["sudo", "launchctl", "bootout", "system/example"],
                    "category": "service-management",
                    "confidence": "heuristic",
                    "effective_argv": ["launchctl", "bootout", "system/example"],
                    "line": 3,
                    "name": "launchctl bootout",
                    "path": "scripts/maintain.sh",
                    "privileged": True,
                    "reason": "launchctl bootout",
                    "target": "host:service-management",
                    "tool": "launchctl",
                }
            ],
        )

    def test_summarize_host_mutator_records_groups_category_and_tool(self):
        records = host_mutator_records_from_observations(
            [
                host_mutation_observation(
                    source_id="scripts/maintain.sh#host-mutation:4:rm",
                    path="scripts/maintain.sh",
                    line=4,
                    name="rm",
                    target="host:filesystem-mutation",
                    category="filesystem-mutation",
                    tool="rm",
                    privileged=True,
                    reason="rm host filesystem path",
                    argv=["sudo", "rm", "-rf", "/Library/Caches/example"],
                    effective_argv=["rm", "-rf", "/Library/Caches/example"],
                ),
                host_mutation_observation(
                    source_id="scripts/maintain.sh#host-mutation:5:rm",
                    path="scripts/maintain.sh",
                    line=5,
                    name="rm",
                    target="host:filesystem-mutation",
                    category="filesystem-mutation",
                    tool="rm",
                    privileged=False,
                    reason="rm host filesystem path",
                    argv=["rm", "-rf", "~/Library/Caches/example"],
                    effective_argv=["rm", "-rf", "~/Library/Caches/example"],
                ),
                host_mutation_observation(
                    source_id="scripts/maintain.sh#host-mutation:2:package",
                    path="scripts/maintain.sh",
                    line=2,
                    name="brew install",
                    target="host:package-management",
                    category="package-management",
                    tool="brew",
                    privileged=False,
                    reason="brew install",
                    argv=["brew", "install", "postgresql"],
                    effective_argv=["brew", "install", "postgresql"],
                ),
            ]
        )

        summaries = summarize_host_mutator_records(records)

        self.assertEqual(
            host_mutator_summaries_to_jsonable(summaries),
            [
                {
                    "category": "filesystem-mutation",
                    "count": 2,
                    "privileged_count": 1,
                    "tool": "rm",
                },
                {
                    "category": "package-management",
                    "count": 1,
                    "privileged_count": 0,
                    "tool": "brew",
                },
            ],
        )

    def test_format_host_mutator_summary_table_uses_count_columns(self):
        records = host_mutator_records_from_observations(
            [
                host_mutation_observation(
                    source_id="scripts/maintain.sh#host-mutation:4:rm",
                    path="scripts/maintain.sh",
                    line=4,
                    name="rm",
                    target="host:filesystem-mutation",
                    category="filesystem-mutation",
                    tool="rm",
                    privileged=True,
                    reason="rm host filesystem path",
                    argv=["sudo", "rm", "-rf", "/Library/Caches/example"],
                    effective_argv=["rm", "-rf", "/Library/Caches/example"],
                )
            ]
        )

        table = format_host_mutator_summary_table(
            summarize_host_mutator_records(records)
        )

        self.assertEqual(
            table,
            "\n".join(
                [
                    "category             tool  count  privileged_count",
                    "filesystem-mutation  rm    1      1",
                ]
            ),
        )


def host_mutation_observation(
    *,
    source_id,
    path,
    line,
    name,
    target,
    category,
    tool,
    privileged,
    reason,
    argv,
    effective_argv,
):
    return RawObservation(
        kind="shell.host_mutation",
        source_id=source_id,
        path=path,
        start_line=line,
        end_line=line,
        name=name,
        target=target,
        confidence="heuristic",
        extractor="fixture-shell",
        extractor_version="0.1.0",
        metadata={
            "argv": argv,
            "category": category,
            "effective_argv": effective_argv,
            "privileged": privileged,
            "reason": reason,
            "tool": tool,
        },
    )


if __name__ == "__main__":
    unittest.main()
