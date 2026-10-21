# NAVIGATION38: CI55 D9-A correction

CI55 (run 39521873109, attempt 1) executed and failed for staging
`bae3e008ff12eec8f00a16c09e3e225e2985672e`, tested through PR merge
`0c8cfdf1b700e6bbc41d9785a94867a97716b294`. Six jobs passed; unit and staging
integration failed. Unit had 12 failures and integration M had 13. The complete
unit measurement reported 93.92% lines and 87.98% branches. Integration measurement
was incomplete, with one ordinary Python child missing its terminal receipt;
the abrupt leg was blocked downstream. No integration coverage is accepted.

This correction restores standalone dump target validation before credential-
dependent maintenance setup. Existing positive fixtures provide explicit backup
format, provenance, TOC and maintenance context; streaming archive assertions use
stdin. The real graph-upgrade case uses the owned PostgreSQL harness and actual
maintenance authority. The inherited-output deadline fixture uses a native sleep
descendant and a bounded termination observation, preserving its cleanup checks.
The public-only lineage test expects the four audited transitions after NAV37's
approved append and retains every exact recovered-proof assertion and negative.

Production refusal guards, integrity checks and endpoint-scoped custody remain
enforced. Coverage instrumentation, M/A validators, hard thresholds, historical
authority records, baselines, debt ceilings, workflows and package versions
remain unchanged.
D9-A remains the approved boundary. D9-B extension replay and production
pgvector admission remain outside this correction.

The commit's Verification block records the exact scoped unit and containerized
integration selectors and executed results. Scoped commands use --no-coverage;
no complete local suite override exists and complete-suite/Python-coverage
execution counts are zero. These checks establish the selected behavior, while
whole-population qualification remains hosted-pending for the new candidate.
Targets remain 87/87 unit and 82/82 integration, above unchanged hard gates 85/85
and 80/80. The operator's AVAILABLE state permits one authorized staging retry
through the existing PR's normal automatic pipeline; it grants no public-main
promotion or duplicate manual trigger.
