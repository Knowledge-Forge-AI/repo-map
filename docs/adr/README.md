# Architecture Decision Records

RepoMap ADRs are organized by the local calendar year and month in which the
logical document was first introduced to the repository.

```text
docs/adr/YYYY/MM/NNNN-<slug>.md
```

Use the introducing commit's committer timestamp and preserve the calendar
date encoded in that timestamp's numeric offset. Do not convert the timestamp
to UTC or to the reviewing machine's timezone. Later edits or moves do not
change the assigned introduction month.

ADR numbers form an independent, repository-global four-digit sequence. Keep
assigned numbers and basenames stable, never reuse a number, allocate the next
number from accepted `main`, and update active repository links during an
authorized move.

[`ADR 0042: Daily ADR and Status Archive Layout`](2026/07/0042-daily-adr-and-status-archive-layout.md)
governs ADR archive structure, numbering stability, and the append-only policy
for this archive. This README does not maintain a "latest ADR" pointer;
sequence and latest-number authority comes from the highest committed ADR in
the archive.
