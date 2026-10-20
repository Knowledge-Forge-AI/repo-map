# REPOMAP-PRODUCT6-NAVIGATION35-BOUNDED-INVENTORY1

Reviewed metadata preparation for roadmap step 6. The contributor CLI and its
transport helper are stdlib-only tooling; product CLI/MCP behavior is unchanged.

## Completed bounded operation

On 2026-10-20, one unauthenticated GET identity chain and one recursive tree GET
were completed for each fixed candidate. No redirects, retries, per-entry or
implementation/legal blob requests occurred. All eight responses closed and
both operation processes were reaped. The canonical manifests are
[A](nav35-inventory-a.json) and [B](nav35-inventory-b.json).

| Candidate | Fixed commit | Fixed tree | Entries | Raw tree bytes | All four response bytes |
| --- | --- | --- | ---: | ---: | ---: |
| pallets/click 8.1.8 | 934813e4d421071a1b3db3973c02fe2721359a6e | 48a3e9893840b8ad002fc31b14be47a31dfd96ed | 172 | 38,848 | 41,459 |
| pypa/packaging 25.0 | f58537628042c7f29780b9d33f31597e7fc9d664 | f14f13b00345dd5193ffd7bd73f93aa31adc8da4 | 102 | 23,269 | 28,373 |

The tree limit remains 10,000 entries / 2,097,152 raw application-body bytes.
Identity responses each have a 32,768-byte cap. Streaming guards stop at those
ceilings; unknown completeness, truncation, identity drift and malformed data
refuse. Accounting describes HTTPResponse application reads, not physical
network or TLS buffering. A 15-second read deadline is supplemented by the
parent's 120-second operation budget and 10-second cleanup grace; a socket
timeout alone does not bound DNS wall time.

The tool defaults to a network-free plan. Execution requires `--execute`, fixed
`--candidate A|B`, and a new exclusive output/intent. No alternate repository,
URL, reserve C, automatic retry or blob-fetch option is provided. Successful
outputs whitelist identity fields and retain no authors, messages, signatures
or raw response bodies. Gitlinks and symlinks are ineligible and never followed.

## Evidence limits and remaining holds

Provider ref/tag/commit/tree consistency was verified; independent cryptographic
object verification was not performed. Source-path candidates are metadata,
with rights explicitly uncleared and every admission flag false. Click's
`_winconsole.py`, `_compat.py` and `_termui_impl.py`, and packaging's
`src/packaging/licenses/_spdx.py`, remain origin-review holds. No legal text was
retrieved. No corpus, labels, model/runtime, utility measurement or production
admission is established. Step 6 remains in progress; D9/D12/D13/D15 remain open.

An independent dispatcher source review identified nine findings. Closing
amendments addressed them; the parent inspected the complete final source and
fresh evidence. There was no second independent review of the closing bytes.
Development failures remain retained; final scoped success does not erase them.

Exact verification owners are
`src/test/unit/python/tools/retrieval_inventory_metadata.unit.test.py` and
`src/test/int/python/tools/retrieval_inventory_metadata.int.test.py`, through
`tools/run_tests.py --suite unit|int --no-coverage -- <exact owner>` (integration
also uses `--pg-container-port 55433` and the canonical disposable sandbox).
Final private verification passed 9 unit and 2 integration tests. Unit cases
cover fixed pins, strict JSON/tree validation, byte/entry refusals, origin holds,
sanitization and non-claims; loopback integration exercises real HTTP framing,
chunked/incomplete reads, redirects and CLI execution without upstream calls.
Complete local suites and coverage were unselected; no override was provided.

CI Run 53 / attempt 1 passed eight executed jobs for predecessor staging
`12b0d4bcde7d5bcf045a57a41b2f0a9857bece42`, tested merge
`7d80eebbafd09b20f2fcd607aede284dc1977db3`:
unit line/branch 94.212%/88.543%, integration 90.427%/82.865%.
Its same-attempt staging/system evidence was verified. It does not qualify this
new candidate or the optional pgvector profile. Hosted state remains AVAILABLE;
one parent-authorized staging publication requests the normal automatic campaign.
New-candidate full-population qualification and coverage remain pending.

Four new Python owners enter clean strict inventory cohorts. Every incumbent
record, authority/projection proof, debt ceiling, baseline, workflow, runner,
package version and dependency remains unchanged.
