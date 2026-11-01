# REPOMAP-CLOE-CI102REPAIR1 Exit

## Scope

This forward repair addresses the executed CI102 failure at staging
`61932a87b1f9c8364069793fc8520d29958eb1d8`. CI102 reported six unit failures,
three measured-integration failures and five integration setup errors. Its
native system candidate built successfully, then failed the obsolete
btree-only backup/restore expectation. The candidate was not accepted.

The repair updates six affected contracts:

1. PostgreSQL metadata tests use the configured read/status authority and
   verify compact/full parity, sanitized credential refusal and body isolation.
2. Restore-role tests distinguish ordinary SQL from explicit lexical purge,
   preserve access-control statements and verify delete-before-revoke order
   and piped secret input. The default remains the explicit no-purge behavior.
3. Both fixed read-only tool-catalog pins match the 31-tool W3 catalog while
   retaining negative mutation and tool-count checks.
4. Installed-wheel tests bind incumbent and successor migration catalogs to
   their respective sources, preserve every incumbent resource byte and allow
   only the W3 lexical migration to be appended.
5. Disposable PostgreSQL reset removes exactly the owned lexical and public
   schemas. Legacy restore begins with an empty public schema and proves
   forward lexical readiness and access-control isolation.
6. D12 round-trip evidence requires the exact sorted core access methods
   `btree` and `gin` in both databases, unchanged archive hashes, equal fixture
   digests, exactly 2,000 rows and the existing schema/extension/slot guards.
   A real disposable dump/restore executes the maintained system probe.

Additional cohesive tests exercise lexical policy, envelopes and driver
failure contracts as units, and retained publication, real CLI behavior and
native statement-timeout recovery as containerized integration. Synthetic
service/executor responses do not establish integration qualification.

## Verification and boundaries

The phase commit records the exact scoped unit and containerized integration
selectors, results and final source review for this frozen successor, using
`--no-coverage`. Retained static enforcement, topology, file length, compilation,
export and privacy checks accompany those proofs. Complete local unit,
integration, smoke, staging, system and combined suites, local project coverage,
calibration and held-out evaluation are intentionally unselected.

CI102 passed the hard coverage gates: unit branches were 18,506/21,338 and
integration branches 17,328/21,338. The requested margins remain 87% unit and
82% integration for both statements and branches. No local coverage was
measured and no successor margin is claimed; hosted CI measures it.

ADR0131 binds one fresh twentieth native AMD start to CI103 attempt1 through
the existing staging/PR23 pipeline. The nineteen actual starts stay spent.
All dependencies, supplier pins, image recipes, runner policies, product
contracts, migration history, debt ceilings and coverage populations remain
unchanged. No further retry, main promotion, tag or deployment is included.
The successor remains pending hosted qualification after staging publication.
