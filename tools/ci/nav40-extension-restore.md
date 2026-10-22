# REPOMAP-PRODUCT6-NAVIGATION40-EXTENSION-RESTORE1 Exit: bounded extension restore candidate

This staging candidate implements bounded D9-B from
[ADR 0084](../../docs/adr/2026/10/0084-extension-aware-backup-and-restore.md)
and the [restore contract](../../docs/specs/postgresql-extension-restore-contract-v1.md).
It requires an explicit trusted capability declaration and independently qualified
current target. The default remains core-only; production pgvector/D15 admission,
new images or dependencies, and configuration-data replay remain separate.

The new path preflights the complete selected set, installs exact prerequisites,
and replays the unchanged custom archive with its verified private derived TOC.
The backup declaration stays stable across later target qualification. Restore
preserves supported historical rows and least-privileged capability grants.
Invocation ownership governs command settlement and compensating target cleanup;
unsettled outcomes retain private evidence and refuse continuation. A retired
host client or shell leader alone is insufficient proof of remote settlement.
Cleanup retains live or unreaped descendants and uncertain session state for
intervention. Only the exact recorded leader, proved childless while stopped,
is eligible for retirement under the qualified runtime model.

The introducing phase commit records exact scoped unit, core integration and
optional-profile selectors, results and limitations. Integration uses the
canonical disposable sandbox. All local selections use `--no-coverage`; complete
local unit, integration, smoke, staging and system populations are unselected.
Disposable optional-profile evidence does not admit a production capability.
New owners enter the existing quality profiles without increasing incumbent debt
ceilings or altering historical authority and projection proofs.

Hosted qualification is pending for this candidate. CI56's pass applies only to
its predecessor. The requested hosted targets remain 87% line/branch unit coverage
and 82% line/branch integration coverage; hard gates remain 85/85 and 80/80.
Publication uses the existing staging pull request's automatic pipeline.

## Retained scope authority

The operator-approved bounded D9-B phase admits exactly 17 new clean helpers in
the existing T1-future/python_retained ownership. No incumbent module is removed
or reclassified. The scope registry appends this exact manifest/selection
transition with its immutable public predecessor as the source-manifest witness.
Every prior authority record, projection proof, finding count and file-length
ceiling is preserved. The introducing commit records final scoped verification;
new hosted qualification remains pending.
