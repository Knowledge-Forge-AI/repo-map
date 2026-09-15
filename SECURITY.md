# Security Policy

## Supported Versions

RepoMap is pre-release software. Until the first public release, the current
`main` branch is the only supported development line. Historical commits,
tags, snapshots, and private dogfood deployments do not receive a public
support commitment.

| Version | Supported |
| --- | --- |
| `main` (unreleased) | Yes |
| Historical development snapshots | No |

This table will be revised when the first public release defines a release
support policy.

## Reporting A Vulnerability

Do not report a suspected vulnerability through public issues, discussions,
pull requests, or social media.

When this repository is public, use the repository's **Security** page and
select **Report a vulnerability**. If private vulnerability reporting is
temporarily unavailable, do not open a public report; use a pre-established
private maintainer channel.

Include the following information when it is safe to do so:

- the affected version or commit;
- the affected component;
- the conditions required to reproduce the issue;
- the security impact;
- a minimal proof of concept; and
- a suggested mitigation, when known.

Do not include unrelated personal, customer, production, credential, or secret
data. Coordinate disclosure with the maintainers until a fix or disclosure
decision is made.

## What Reporters Can Expect

Maintainers will use a reasonable process that may include:

- acknowledging the report when it is received;
- validating the report and assessing severity;
- requesting additional information when required;
- providing status updates at reasonable milestones;
- coordinating disclosure where appropriate; and
- providing credit when the reporter wants it and it is appropriate.

Response and remediation timing depends on the issue, affected components, and
available evidence.

## Scope

Security reports may cover RepoMap source, release packaging, dependency or
build-chain behavior, and the default local runtime. Relevant impacts include
privilege violations, privacy failures, injection, path traversal, arbitrary
execution, secret exposure, authentication or authorization failures,
publication-integrity failures, and destructive-lifecycle failures.

Dependency findings remain in scope even when the affected tool is used only
during builds. Ordinary bugs without a plausible security impact should use
the normal issue process after the repository is public.

## Disclosure And Good-Faith Boundaries

Test only systems and data that you own or are authorized to use. Avoid privacy
violations, service disruption, data destruction, persistence, and lateral
movement. Stop after establishing the minimum evidence needed to demonstrate
the issue, and allow a reasonable opportunity for coordinated remediation.

These boundaries describe the requested reporting process and do not create
additional legal rights or commitments.
