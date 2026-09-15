# ADR 0006: Project Licensing and Commercialization Strategy

## Status

Accepted

## Date

2026-06-29

## Context

The final Apache-2.0 RepoMap source state is preserved for publication in
[`lair001/repo-map_apache-2.0-final`](https://github.com/lair001/repo-map_apache-2.0-final).
At the licensing cutover, the repository had a `LICENSE` file containing
Apache License 2.0, the README reported
`License: Apache-2.0`, and `pyproject.toml` declared `license =
"Apache-2.0"`.

The project may eventually need a commercialization strategy. That strategy
must distinguish open source use from proprietary terms. GPL-3.0-or-later and
AGPL-3.0-or-later both allow commercial use. A commercial license in a dual
licensing model is not a license merely for "commercial use"; it is a separate
proprietary license for terms the public copyleft license does not provide,
such as closed-source redistribution, private SaaS/network-service
modifications, warranty, indemnity, procurement terms, support commitments, or
other negotiated obligations.

This ADR records the accepted licensing strategy. The cutover is implemented in
a dedicated licensing/documentation/package-metadata phase before Phase C2.

This ADR is not legal advice. Before implementing a license transition or
accepting third-party contributions under a dual-license plan, RepoMap should
use qualified legal review.

## Decision

RepoMap will switch future releases to AGPL-3.0-or-later plus a proprietary
commercial license. The commercial license is for proprietary terms and
commercial-license obligations, not merely for commercial use.

The final Apache-2.0 baseline is the source state preserved for publication in
[`lair001/repo-map_apache-2.0-final`](https://github.com/lair001/repo-map_apache-2.0-final).
Existing Apache-2.0 releases remain available under Apache-2.0. Later RepoMap
development uses the licensing model accepted by this ADR.

Before accepting outside contributions, RepoMap will add contribution
governance that preserves future relicensing options. The initial contribution
terms use a contributor license agreement rather than copyright assignment:
contributors retain copyright while granting Samuel Leighton Lair, as RepoMap
project steward, broad rights to use, modify, distribute, sublicense, and
relicense contributions as part of RepoMap, including under
AGPL-3.0-or-later and commercial licenses.

AGPL is preferred over GPL for a tool that may become valuable as a hosted
analysis service, because AGPL is stronger than GPL for SaaS and
network-service forks: a modified AGPL program that interacts with users over a
network must offer those users the corresponding source.

RepoMap should not use a custom noncommercial source-available license as the
main strategy, and should defer open-core until there is a clear product line
between community and paid features.

## Licensing Facts

GPL and AGPL permit commercial use. Users may run the software commercially,
sell copies, charge for distribution, offer paid support, and use the software
inside businesses, subject to the relevant license obligations.

GPL and AGPL do not permit adding proprietary restrictions when distributing a
covered work under the public license. A separate commercial license can sell
proprietary terms because the copyright holder is granting rights through a
different license, not because commercial use was forbidden by GPL or AGPL.

AGPL is stronger than GPL for network services. GPL generally triggers source
obligations on distribution/conveying. AGPL adds a network interaction
requirement for modified versions that interact with users remotely over a
computer network.

Existing Apache-2.0 releases cannot be clawed back. Apache-2.0 grants
perpetual and irrevocable copyright and patent permissions, subject to its
terms. RepoMap can change the license for future releases only to the extent
the project steward has the necessary rights. Recipients of already-published
Apache-2.0 versions can continue using and forking those versions under
Apache-2.0.

Dual licensing requires copyright control. If third-party contributors retain
copyright and contribute only under Apache-2.0, GPL, or AGPL terms, the project
steward may not have the right to offer their contributions under a separate
proprietary license. Before accepting outside contributions under a future
dual-license strategy, RepoMap needs either copyright assignment or a CLA that
grants broad relicensing rights. A DCO alone is not enough for proprietary
dual licensing.

Noncommercial source-available licenses are not open source. Open source
licenses cannot discriminate against fields of endeavor, including business
use. A noncommercial restriction may be a business choice, but RepoMap should
not present it as open source.

## Options Evaluated

### 1. Keep Apache-2.0

Apache-2.0 maximizes adoption, packaging, enterprise review, downstream
integration, and contribution comfort. It is compatible with RepoMap's current
local deterministic tooling posture and avoids license churn before the product
shape is stable.

Community adoption risk is lowest. Developers, companies, Linux distributions,
and Python packaging users usually understand Apache-2.0.

Monetization risk is highest. Competitors can fork, embed, host, or sell
RepoMap-derived products with minimal sharing obligations. Monetization would
need to come from hosted operations, support, integrations, data services,
enterprise features, brand trust, or execution speed rather than license
leverage.

This was the recommended immediate strategy when ADR 0006 was drafted. It is
superseded by the accepted licensing cutover to AGPL-3.0-or-later plus
commercial licensing for future releases.

### 2. Switch Future Releases to GPL-3.0-or-Later Plus Commercial License

GPL-3.0-or-later would require distributed modified versions and combined
covered works to follow GPL terms, while allowing the copyright holder to sell
a separate proprietary license for users who need closed-source distribution or
other proprietary terms.

Community adoption risk is medium to high. Some users welcome strong copyleft;
others, especially commercial integrators, avoid GPL dependencies or tools that
could complicate redistribution.

Monetization risk is lower than Apache-2.0 for distributed proprietary
embedding, because some proprietary users would need a commercial license.
However, GPL is weaker for SaaS-only forks because modified server-side use
without distribution generally does not require source release.

This is not the preferred copyleft option for RepoMap if hosted graph analysis
or network-service usage becomes strategically important.

### 3. Switch Future Releases to AGPL-3.0-or-Later Plus Commercial License

AGPL-3.0-or-later would keep GPLv3-style copyleft and add network interaction
coverage for modified server-side versions. A proprietary commercial license
could then be sold to users who want closed-source redistribution,
closed-source hosted modifications, support, warranty, indemnity, or other
negotiated terms.

Community adoption risk is highest among standard open source licenses in this
ADR. Some companies prohibit AGPL use or require special legal approval.
Potential contributors may worry that their work supports a commercial
licensing funnel unless governance is explicit and fair.

Monetization leverage is highest among the open source options. AGPL reduces
the SaaS loophole that GPL leaves open and makes proprietary hosted forks more
likely to need a commercial license.

This is the accepted future-release strategy. It applies only to releases after
the final Apache-2.0 source state preserved for publication in
`lair001/repo-map_apache-2.0-final`, and it is paired with contribution
governance that grants the maintainer commercial relicensing rights for new
contributions.

### 4. Use a Custom Noncommercial Source-Available License

A custom noncommercial source-available license can reserve commercial
exploitation to the project steward and may feel attractive for monetization.
It should not be called open source because it restricts fields of endeavor.

Community adoption risk is very high. Custom licenses increase legal review
cost, reduce ecosystem trust, block some package distribution channels, and
make casual contribution less likely.

Monetization risk is also high. The license may deter exactly the companies
that could become buyers, and custom wording creates enforceability and
compatibility uncertainty.

This option is rejected for RepoMap's main licensing strategy.

### 5. Use Open-Core Instead of Dual Licensing

Open-core would keep a permissive or copyleft community core and reserve
selected features for a proprietary product. It can coexist with Apache-2.0,
GPL, or AGPL for the community edition.

Community adoption risk depends on the boundary. It is lower when the open core
is genuinely useful and the paid layer is clearly enterprise/operations work.
It is high if the core feels intentionally incomplete or if features move
behind a paywall after users depend on them.

Monetization risk is medium. Open-core can work when paid features are obvious,
such as hosted collaboration, enterprise auth, compliance reporting, managed
storage, private deployment tooling, or organization-wide analysis. RepoMap's
current feature boundaries are not stable enough to choose this split now.

This option is accepted only as a later product strategy to revisit, not as the
near-term licensing answer.

## Required File Changes If Accepted

The licensing implementation slice must update at least these files or
artifacts:

- `LICENSE`: replace or supplement Apache-2.0 with the selected public license
  text and any commercial-license pointer needed for dual licensing.
- `README.md`: update the license section, project identity, contribution
  expectations, and any commercial-license contact text.
- `CONTRIBUTING.md`: add contribution license requirements, CLA or copyright
  assignment workflow, and sign-off/review rules.
- Contributor agreement: add a CLA or copyright assignment document before
  accepting outside contributions.
- Source-file headers, if used: add explicit SPDX and copyright notices, or
  update existing notices.
- `pyproject.toml`: update the `license` metadata and any relevant package
  classifiers or license files.

The same implementation slice should also audit release artifacts, generated
packages, docs, example files, and CI checks for stale Apache-2.0 references.

## Contribution Governance

RepoMap should not accept outside code contributions that could block a future
dual-license transition. Before opening broad contribution intake, choose one
of these models:

- Copyright assignment to the project steward.
- CLA granting the project steward nonexclusive, irrevocable rights to
  sublicense and relicense contributions, including under proprietary terms.

The governance text must be honest. Contributors should know whether their
work may be used in proprietary commercial licenses. If RepoMap stays
Apache-2.0 permanently, a lighter contribution process may be enough. If
RepoMap wants AGPL/commercial dual licensing, copyright control is not optional.

## Risks to Community Adoption

Apache-2.0 has the strongest adoption profile but the weakest license-based
business protection.

GPL increases philosophical clarity and reciprocity but can reduce enterprise
and library-style adoption.

AGPL gives the strongest open-source reciprocity for hosted forks but can trip
corporate policy bans and discourage embedded use.

Custom source-available licensing can make RepoMap feel less trustworthy,
especially if users expected open source.

Open-core can work, but only if the community edition remains complete enough
to be respected on its own.

## Risks to Monetization

Apache-2.0 leaves most license-based monetization on the table, so revenue must
come from execution, hosted service quality, enterprise trust, integrations,
support, or brand.

GPL/commercial dual licensing may monetize proprietary distribution but does
less to capture hosted-service forks.

AGPL/commercial dual licensing offers stronger leverage for SaaS-style
competition but may shrink the top of the adoption funnel.

Custom noncommercial licensing may look protective but can reduce both
adoption and buyer confidence.

Open-core requires disciplined product management. If the paid boundary is
unclear or moves too often, it can harm trust without producing durable revenue.

## Recommendation for RepoMap

Switch future RepoMap releases to AGPL-3.0-or-later plus a commercial
proprietary license before Phase C2. Use the commercial license for proprietary
terms, not as permission for commercial use.

Preserve the final Apache-2.0 RepoMap source state for publication in
[`lair001/repo-map_apache-2.0-final`](https://github.com/lair001/repo-map_apache-2.0-final).
Code released under Apache-2.0 remains available under Apache-2.0, and those
prior grants are not revoked by the later RepoMap licensing model.

Add contribution governance before accepting outside contributions. The
project should not accidentally lose the ability to dual license future work.

Do not use a custom noncommercial source-available license for RepoMap's main
line. Defer open-core until paid feature boundaries are concrete and the open
core is demonstrably useful on its own.

## Non-Goals

This ADR and its implementation do not:

- change storage code;
- change CLI behavior;
- start Phase C2;
- relicense prior Apache-2.0 releases;
- revoke prior Apache-2.0 grants;
- add source-file headers;
- authorize accepting outside contributions without contribution governance;
  or
- decide pricing, support tiers, hosted-service terms, or trademark policy.

## References

- Apache License, Version 2.0:
  <https://www.apache.org/licenses/LICENSE-2.0>
- GNU, Selling Free Software:
  <https://www.gnu.org/philosophy/selling.en.html>
- GNU GPL FAQ:
  <https://www.gnu.org/licenses/gpl-faq.html>
- GNU Affero General Public License:
  <https://www.gnu.org/licenses/agpl-3.0.en.html>
- Open Source Initiative, The Open Source Definition:
  <https://opensource.org/osd>
