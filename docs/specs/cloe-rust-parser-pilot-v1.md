# CLOE Rust parser pilot v1

Phase: `REPOMAP-CLOE-RUST-PILOT1`.

Decision: [ADR 0155](../adr/2026/11/0155-isolated-rust-source-parser-pilot.md),
under [ADR 0050](../adr/2026/08/0050-extractor-dependency-and-capability-architecture.md),
[ADR 0154](../adr/2026/11/0154-extractor-capability-receipt-foundation.md)
and [ADR 0071](../adr/2026/09/0071-post-promotion-local-server-cloud-architecture.md).

Foundation: [CLOE extractor capability foundation v1](cloe-extractor-capability-foundation-v1.md).

Status: **accepted design contract; implementation gates remain open.** No
source implementation, native import or qualification is asserted here.
Each section names its gate.

All paths below are relative to `src/main/python/common_lore_index/` unless
they start with `src/`, `tools/`, `docs/` or `.github/`.

## 1. Evidence tiers

| Tier | What it can prove | What it cannot prove |
|---|---|---|
| T1 fake protocol | Parent logic: selection, framing, validation, canonical vocabulary, gating, storage and readback, refusals | Anything about the native parser, the container or the platform |
| T2 native component | This exact runtime, image, platform, construction, containment and fixture-correctness evidence for one declared attempt | Product readiness, other platforms, bare metal, container-free Local |
| T3 product acceptance | Not claimed by this pilot | — |

A T1 pass is never reported as T2. A T2 pass is never reported as dependency
adoption, W6 closure or release acceptance.

## 2. Component lock (`extractors/rust_pilot/component_lock.py`)

Schema `cloe-rust-pilot-component-lock-v1`, lock identity `rust-pilot-lock-1`.
The lock digest is the SHA-256 of the canonical JSON of the lock constants:
sorted keys, `(",", ":")` separators and ASCII. The lock is Python source, so
it needs no new package data.

### 2.1 Exact artifacts

| Package | CPU | Filename | Size | SHA-256 |
|---|---|---|---|---|
| tree-sitter 0.26.0 | aarch64 | `tree_sitter-0.26.0-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl` | 639334 | `8ff2e0750b7daa722302838356d7b65e303829b7eb73c915df127ddba115e1d1` |
| tree-sitter 0.26.0 | x86_64 | `tree_sitter-0.26.0-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` | 668102 | `7075ef857ef86f327dbb72d1e2574dda78db5754b3a1fca6506acd7fe5d561a7` |
| tree-sitter-rust 0.24.2 | aarch64 | `tree_sitter_rust-0.24.2-cp39-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl` | 170310 | `9d76d1208c3638b871236090759dfc13d478921320653a6c9da5336e7c58f65a` |
| tree-sitter-rust 0.24.2 | x86_64 | `tree_sitter_rust-0.24.2-cp39-abi3-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl` | 164706 | `e033c5a93b57c88e0a835880de39fc802909ff69f57aaff6000211c196ea5190` |

The URLs are the exact `files.pythonhosted.org` URLs recorded in the frozen
proposal metadata. They are used only by the AMD acquisition in §15. No sdist,
other version, index query, extra or fallback URL exists.

### 2.2 Closed member set

Each wheel's members are exactly the following. Digests come from the parent's
inert inspection, and the lock repeats them byte for byte.

**tree-sitter 0.26.0**, identical on both architectures:

| Member | Size | SHA-256 |
|---|---|---|
| `tree_sitter/__init__.py` | 1504 | `0754ef72…` |
| `tree_sitter/__init__.pyi` | 13390 | `54ccd48b…` |
| `tree_sitter/py.typed` | 0 | `e3b0c442…` |
| `tree_sitter-0.26.0.dist-info/METADATA` | 10026 | `40c7146e…` |
| `tree_sitter-0.26.0.dist-info/top_level.txt` | 12 | `a0d28314…` |
| `tree_sitter-0.26.0.dist-info/licenses/LICENSE` | 1088 | `1af07905…` |

**tree-sitter 0.26.0**, per architecture:

| Member | aarch64 size, SHA-256 | x86_64 size, SHA-256 |
|---|---|---|
| `tree_sitter/_binding.cpython-313-<arch>-linux-gnu.so` | 2032984, `7e14540f…` | 2062280, `92d8e6c4…` |
| `tree_sitter-0.26.0.dist-info/WHEEL` | 193, `4c0e41a9…` | 190, `e13ee838…` |
| `tree_sitter-0.26.0.dist-info/RECORD` | 780, `b0739118…` | 779, `4ce4a101…` |

**tree-sitter-rust 0.24.2**, identical on both architectures:

| Member | Size | SHA-256 |
|---|---|---|
| `tree_sitter_rust/__init__.py` | 942 | `39c67279…` |
| `tree_sitter_rust/__init__.pyi` | 138 | `c58d914a…` |
| `tree_sitter_rust/binding.c` | 679 | `cdfd53e3…` |
| `tree_sitter_rust/py.typed` | 0 | `e3b0c442…` |
| `tree_sitter_rust/queries/highlights.scm` | 3527 | `0f034310…` |
| `tree_sitter_rust/queries/injections.scm` | 247 | `723146f1…` |
| `tree_sitter_rust/queries/tags.scm` | 1194 | `f22867fd…` |
| `tree_sitter_rust-0.24.2.dist-info/METADATA` | 2793 | `218755ae…` |
| `tree_sitter_rust-0.24.2.dist-info/top_level.txt` | 26 | `ea9d18a4…` |
| `tree_sitter_rust-0.24.2.dist-info/licenses/LICENSE` | 1080 | `31d5b6f4…` |

**tree-sitter-rust 0.24.2**, per architecture:

| Member | aarch64 size, SHA-256 | x86_64 size, SHA-256 |
|---|---|---|
| `tree_sitter_rust/_binding.abi3.so` | 1389144, `d0911732…` | 1266544, `a9651120…` |
| `tree_sitter_rust-0.24.2.dist-info/WHEEL` | 187, `0f94b7b5…` | 180, `3e551b29…` |
| `tree_sitter_rust-0.24.2.dist-info/RECORD` | 1163, `4403d3c9…` | 1163, `56399f28…` |

The lock module holds the full 64-hex digests; the abbreviations above are for
reading only. `RECORD` must list every other locked regular member with its
exact `sha256=<urlsafe-b64>` and length, and list itself with empty fields.
The held wheels also contain explicit directory metadata. A directory entry is
not a locked member and is admitted only when it is unique, slash-terminated,
empty, stored or deflated under the admitted compression check, mode `0755`,
non-symlink and a proper parent of a locked regular member. Directory entries
are excluded from `RECORD` obligations; the host and guest derive the sealed
parent directories from the verified regular members. Nothing else is admitted,
including:

- additional regular members;
- directory entries outside those exact proper parents, or any directory/file
  path collision;
- symlink or special-file external attributes;
- absolute names, `..`, backslashes or duplicate names;
- `.pth` files, `entry_points.txt`, `*.data/` directories or other top-level
  names;
- encryption flags;
- compression other than stored or deflate;
- more than 8 MiB uncompressed per archive.

The lock also records, per extension, the inert ELF facts: machine 183 or 62,
non-executable `GNU_STACK`, RELRO, `DT_NEEDED` exactly `libc.so.6` and
`libpthread.so.0`, and the observed `GLIBC_*` version strings. These are
static observations, not runtime pairing.

### 2.3 Notices

`third_party_licenses/tree-sitter-core-LICENSE.txt` holds the MIT text of the
vendored Tree-sitter C core at commit `7f534862c3ec939c3a6ee147f7600ef5c1bf900f`.
The wheels do not carry it.

`third_party_licenses/tree-sitter-rust-pilot-source.json` records:

- both packages, their tags and their upstream license text digests;
- the core commit;
- the 404 provenance observations;
- that RepoMap does not redistribute the wheels.

`third_party_licenses/tree-sitter-unicode-LICENSE.txt` also holds the complete
upstream `lib/src/unicode/LICENSE` at that same declared core commit. Its ICU
58+ Unicode Data Files and Software notice covers the included Unicode
headers. Retaining its historical notices does not assert that their
dictionary/conversion components occur in the wheel or establish source
reproduction. All three files use existing package-data patterns. Setup
injects both supplemental notice texts under `notices/`; host/readback
verification includes their exact bytes. No wheel member or `RECORD` changes.
MIT and Unicode notice conditions are retained. Project AGPL-3.0-or-later
and separate commercial licensing remain unchanged.

## 3. Prepared profile (`extractors/rust_pilot/prepared_profile.py`)

A prepared profile is a host directory, created before indexing by an explicit
`prepare` operation, for exactly one CPU. The directory:

- is owned by the effective user, mode `0700`;
- contains exactly three regular, single-link, `0600` entries:
  - `profile.json`, schema `cloe-rust-pilot-prepared-profile-v1`, with keys
    `cpu`, `lock_id`, `lock_sha256` and `wheels` (filename, size and SHA-256
    for the two wheels);
  - the two exact wheel files for that CPU.

`prepare` copies verified bytes from an operator-supplied source directory:
private custody for ARM, or the §15 AMD download directory. It writes through
ADR 0154 bounded no-follow IO with exclusive creation. It never downloads.

At run start, the parent verifies the profile:

- exact directory listing;
- bounded no-follow reads, using the 1 MiB `bounded_io` cap, which both wheels
  satisfy;
- size and digest equality with the lock;
- the closed-member check in memory (§2.2);
- the CPU equals the Docker server architecture.

Any failure, or an absent directory, records exactly one run-level
`dependency_unavailable` outcome and refuses the run's Rust parsing. There is
no reacquisition, fallback or partial profile. The profile digest is the
SHA-256 of `profile.json`'s bytes.

## 4. Selection and classification (`extractors/rust_pilot/selection.py`)

Rule `rust-pilot-selection-v1` applies to the `FileInfo` inventory that legacy
discovery produced in the same run.

| Condition | Outcome (one per path) |
|---|---|
| Path does not end in `.rs` | not selected; no record |
| Symlink, non-regular, or not openable no-follow under the root | `selection_refused` |
| Size > 1,048,576 bytes | `resource_bound_exceeded` (input); no container |
| SHA-256 of read bytes ≠ discovery `content_hash`, or stat changes during the read | `source_changed` |
| Bytes are not strict UTF-8 | `input_not_utf8`; no container |
| Otherwise | selected for parsing |

The legacy `file` observation and node for every `.rs` path stay byte-identical
whether or not the pilot runs. Their language stays `unknown`. Generated and
test roles are parsed and keep their legacy role.

The basename `build.rs` sets `build_script_name: true` on the Rust source node.
The file is parsed as text only; no build script, `cargo`, `rustc` or macro is
ever run. A UTF-8 BOM is retained in the bytes and does not shift byte offsets.

## 5. Container construction (`extractors/rust_pilot/docker_boundary.py`, `construction.py`)

### 5.1 Docker client

The pilot API takes an explicit absolute path to the Docker client. The tool
layer obtains it from an explicit argument, records it, and runs
`docker version` once per run. That records the server OS, which must be
`linux`, and the architecture.

The client inherits the parent's Docker configuration and context. No
container ever receives a Docker socket. Every client call has its own
subprocess timeout (20 s) inside the phase budgets of §7. The image is the
exact `sha256:` ID supplied by the caller. `docker image inspect` must report:

- that ID;
- OS `linux` and the profile's architecture;
- an empty `Config.Volumes`;
- `/usr/local/bin/python3.13` present (checked by the probe).

### 5.2 Create

One container per selected file, plus one run-level probe container (§5.6).
Each is created with exactly this argument vector:

```text
docker create --rm --name repomap-rust-pilot-<run12>-<seq6>
  --label org.repomap.rust-pilot.run=<run_id>
  --label org.repomap.rust-pilot.seq=<seq>
  --platform linux/<arm64|amd64> --pull never
  --network none --ipc none --read-only
  --cap-drop ALL --security-opt no-new-privileges=true
  --pids-limit 32 --memory 512m --memory-swap 512m
  --ulimit core=0 --ulimit nofile=64:64
  --user 10001:10001 --workdir /scratch --env LC_ALL=C.UTF-8
  --log-driver none --stop-timeout 1
  --tmpfs /opt/repomap-rust:rw,exec,nosuid,nodev,size=16m,mode=0755,uid=0,gid=0
  --tmpfs /scratch:rw,noexec,nosuid,nodev,size=4m,mode=0700,uid=10001,gid=10001
  --entrypoint /usr/local/bin/python3.13
  sha256:<sdk-image-id> -I -S -B -c "import time; time.sleep(75)"
```

The run identity and sequence values:

- `run_id` is `rp1.` plus the first 16 hex digits of SHA-256 of the run nonce;
- `run12` is the first 12 of those hex digits;
- `seq` is the per-run container ordinal, and `seq6` is that ordinal
  zero-padded to six digits.

The command line has no `-v`, `--mount`, `--privileged`, `--device`,
`--network` other than `none`, seccomp or AppArmor override, host PID/IPC/UTS
namespace or environment passthrough. A name collision refuses; foreign
containers are never removed.

PID 1 is the non-root sleeper. Its 75 s lifetime is a dead-man bound: if the
parent dies, the container exits and `--rm` removes it.

After `docker start`, `docker container inspect <id>` must show:

- the exact image ID;
- `ReadonlyRootfs`;
- `NetworkMode=none`;
- `CapDrop=[ALL]` and empty `CapAdd`;
- `no-new-privileges`;
- `Privileged=false`;
- the PID and memory limits;
- exactly the two tmpfs entries;
- empty `Mounts`;
- user `10001:10001`;
- the labels.

From then on, every operation addresses the full 64-hex container ID.

### 5.3 Setup (trusted, setup-only principal)

`docker exec -i -u 0:0 -w / <id> /usr/local/bin/python3.13 -I -S -B -c
<guest/setup_writer.py source>`

The writer source is RepoMap package text loaded through `importlib.resources`
and passed as one argument; it stays well under the 128 KiB per-argument
limit. Its stdin carries, in order:

1. A magic line `REPOMAP-RUST-SETUP-1`.
2. One JSON header line of at most 64 KiB, listing each payload with its
   destination class (`wheel`, `helper` or `notice`), size and SHA-256, and the
   closed member list per wheel.
3. The payload bytes, back to back: the two wheels, `parse_helper.py` and the
   core and Unicode notices. Their total is at most 4 MiB.

The writer:

1. Verifies each payload's size and digest, and the archive rules of §2.2,
   including the bounded directory metadata exception, in memory.
2. Writes members under `/opt/repomap-rust/site/`, the helper as
   `helper/parse_helper.py` and the notice as
   `notices/tree-sitter-core-LICENSE` and `notices/tree-sitter-unicode-LICENSE`.
   It traverses with
   `O_DIRECTORY|O_NOFOLLOW` directory descriptors, uses `mkdirat`, and creates
   files with `O_CREAT|O_EXCL|O_NOFOLLOW` at `0600`, writing fully.
3. Seals with `fchmod`: directories `0555`, regular files `0444`, the two
   `.so` files `0555`. Owner and group stay `0:0`.
4. Prints a single summary line and exits 0.

Root without capabilities can write and chmod its own tmpfs entries but has no
`CAP_DAC_OVERRIDE`, `CAP_CHOWN`, `CAP_FOWNER` or `CAP_SYS_ADMIN`. The non-root
parser cannot write or re-permission the sealed tree. The setup principal's
lifetime is this one exec. No root exec occurs after it, and setup never
receives target bytes. The parent does not trust the writer's summary.

### 5.4 Install readback (parent-verified)

`docker exec -u 10001:10001 <id> /usr/local/bin/python3.13 -I -S -B -c
<guest/install_readback.py source>`, with stdin closed.

The reader:

- walks `/opt/repomap-rust` in sorted order with `lstat` and no following;
- emits a JSON header per entry (path, type, mode, uid, gid, link count, size)
  and the raw bytes of each regular file;
- refuses a symlink, a special file or more than 8 MiB of output;
- emits the `/proc/self/mountinfo` lines for `/`, `/opt/repomap-rust` and
  `/scratch`;
- emits the `Uid`, `Gid`, `Cap*`, `NoNewPrivs` and `Seccomp` lines of
  `/proc/self/status`;
- emits the `/scratch` listing, `socket.if_nameindex()` and bounded Linux
  interface flags and IPv4/IPv6 address-presence facts.

The parent requires:

- the path set equals the expected tree from its own in-memory extraction:
  wheel members, helper and both supplemental notices;
- every file's bytes are identical;
- the exact modes of §5.3, uid and gid 0, and one link per file;
- `/` is `ro`;
- `/opt/repomap-rust` is `exec,nosuid,nodev`;
- `/scratch` is `noexec,nosuid,nodev`;
- uid and gid 10001;
- `CapEff`, `CapPrm` and `CapAmb` are zero;
- `NoNewPrivs` is 1;
- `/scratch` is empty;
- loopback is present; only `tunl0` and `ip6tnl0` may additionally be present,
  with the UP flag clear and no IPv4 or IPv6 address. Missing or ambiguous
  observations for these fallback devices refuse, as does any other name.
  Their presence on the native guest remains unverified until qualification.

Mount and credential lines are guest-reported. The parent cross-checks them
with the host-side inspection of §5.2 and labels them `guest_observed`.

### 5.5 Parse exec

`docker exec -i -u 10001:10001 -w /scratch <id> /usr/local/bin/python3.13 -I
-S -B -X utf8 /opt/repomap-rust/helper/parse_helper.py`

The helper replaces the module path with exactly the runtime site directory
followed by the interpreter's standard-library entries. It imports
`tree_sitter` and `tree_sitter_rust` through `importlib.import_module`; this
is the single admitted dynamic-import site. It then runs §6.

`-I -S` excludes `PYTHON*` environment variables, user site and every
site-packages directory, so no `.pth` file is processed and no image-installed
distribution can shadow the pair.

### 5.6 Run-level probe container

Before the first target file, one container is constructed exactly as in
§5.2–§5.4. It then runs:

1. `guest/runtime_probe.py`, as the parser UID. In stdlib-only order it
   records:
   - `sys.executable`, `sys.version`, `sys.implementation.cache_tag`,
     `sysconfig` `SOABI` and `sys.abiflags`;
   - `platform.machine()` and `platform.libc_ver()`;
   - `os.uname().release`;
   - the file-system and preferred encodings, `sys.flags` and `LC_ALL`.

   It then imports the pair and records:
   - `tree_sitter.__version__`, `LANGUAGE_VERSION` and
     `MIN_COMPATIBLE_LANGUAGE_VERSION`;
   - the module file paths;
   - `Language.abi_version`;
   - `id_for_node_kind` for every kind in §6.3;
   - `field_id_for_name` for `name`, `type`, `trait` and `body`.

   It uses no `Point`, `Query` or parse call.
2. The parse helper on the RepoMap-owned probe source, an original synthetic
   text of more than 300 lines with an item whose name starts past column 300.
   The text and its gold are constants in the host module
   `extractors/rust_pilot/probe_material.py`. The helper's output must match
   that gold exactly.

The parent requires:

- `/usr/local/bin/python3.13` and version `3.13.12` for this SDK image;
- cache tag `cpython-313`;
- SOABI `cpython-313-<cpu>-linux-gnu` and an empty `abiflags`;
- the machine equal to the profile CPU;
- glibc of at least 2.28;
- `__version__ == "0.26.0"`;
- `MIN_COMPATIBLE_LANGUAGE_VERSION <= abi_version <= LANGUAGE_VERSION` and
  `abi_version == 15`, the grammar header's `LANGUAGE_VERSION`;
- every kind and field id present;
- module files under `/opt/repomap-rust/site`.

Interpreter and runtime values are recorded as observations. They are not
pins: the kernel is not pinned, and image identity is not bitwise APT
reproducibility. Any mismatch refuses the run before target bytes exist; this
is `inadmissible` with no Rust claims.

## 6. Helper protocol (`extractors/rust_pilot/helper_protocol.py`, `guest/parse_helper.py`)

### 6.1 Input

The parent writes one ASCII line of at most 256 bytes:

```text
{"n":<len>,"nonce":"<64 hex>","sha256":"<64 hex>","v":1}
```

It then writes exactly `n` bytes and closes stdin.

The helper reads the line with a limit, validates its exact keys, and reads
exactly `n` bytes. It confirms end of file, checks the SHA-256, and exits 3
without output on any mismatch.

The `nonce` is the per-file invocation nonce: SHA-256 of the run nonce, the
sequence number and the input digest. It exists only in parent memory and the
helper's stdin.

### 6.2 Parsing

The helper makes one `Parser(Language(tree_sitter_rust.language())).parse(data)`
call with the `bytes` overload. Traversal is a single `TreeCursor`
depth-first walk that:

- descends only into the root, `mod_item` and `foreign_mod_item` bodies
  (`declaration_list`), and `impl_item` and `trait_item` bodies;
- never descends into function bodies, expressions or `ERROR` nodes;
- has a depth cap of 256 scopes and a visited-node cap of 2,000,000; reaching
  either sets `truncated`.

Outer `attribute_item` nodes are preceding siblings of declarations. The
cursor retains up to16 pending attribute ranges per scope, associates them
with the next item, and clears them when that item or an unsupported
non-trivia construct consumes the position. `line_comment` and `block_comment`
are ignored as trivia, preserving pending attributes across comments; doc
comments are not a semantic attribute claim. A dangling attribute is counted
as unsupported. Exceeding16 marks explicit truncation, never silent complete
attribute metadata. Attribute ranges contain the entire `#[...]` token;
retained Python derives its bounded path prefix from those exact bytes.

Permitted node members are:

- `type`, `start_byte`, `end_byte`;
- `has_error`, `is_error`, `is_missing`, `is_named`;
- `child_by_field_name` for `name`, `type`, `trait` and `body`;
- cursor navigation (`goto_first_child`, `goto_next_sibling`, `goto_parent`)
  and `cursor.node`.

Forbidden anywhere in the helper:

- `start_point`, `end_point`, `range`, `Point`, `Range`, `row`, `column`;
- `Query`, `QueryCursor`;
- `edit`, `walk` on non-root nodes, `parent`, `child_with_descendant`;
- `descendant_for_point_range` and `named_descendant_for_point_range`;
- `print_dot_graph` and `print_dot_graphs`;
- `logger`, `included_ranges`, read callbacks, `progress_callback`;
- `text`, `copy`, `reset`;
- a second `parse` call.

A unit source guard parses the helper's AST and fails on any of these names, a
second `parse` call, or any non-`bytes` argument shape. This is avoidance of
known defect 472, not a memory-safety proof.

### 6.3 Output frames

The output is ASCII newline-terminated JSON objects, each at most 512 bytes,
4 MiB and 50,000 frames in total. Every value is an integer, except the tag
`t`, `nonce` and the hello `ts` version string.

| `t` | Exact keys | Meaning |
|---|---|---|
| `hello` | `t v nonce ts abi` | First frame. `ts` and `abi` are helper-reported and informational only |
| `n` | `t i p k s e n a v y r f` | Item `i` (dense from 0); parent item `p` or −1; tag `k`; byte range `s`,`e`; name range `n` = `[s,e]` or `null`; attribute path ranges `a` (≤ 16 pairs); visibility range `v`; impl self type `y`; impl trait `r` (the last three nullable); flags `f` |
| `u` | `t p k s e` | Unsupported construct tag `k` at range `s`,`e` in scope `p` |
| `end` | `t nonce root_error errors missing items unsupported truncated` | Last frame. Counts are integers; `root_error` and `truncated` are 0 or 1 |

Item tags:

| Tag | Grammar kind |
|---|---|
| 1 | `mod_item` |
| 2 | `function_item` |
| 3 | `function_signature_item` |
| 4 | `struct_item` |
| 5 | `enum_item` |
| 6 | `union_item` |
| 7 | `type_item` |
| 8 | `trait_item` |
| 9 | `impl_item` |
| 10 | `macro_definition` |

Unsupported tags:

| Tag | Construct |
|---|---|
| 1 | Item-position `macro_invocation` |
| 2 | `const_item` |
| 3 | `static_item` |
| 4 | `use_declaration` |
| 5 | `extern_crate_declaration` |
| 6 | Foreign function or static inside `foreign_mod_item` |
| 7 | `inner_attribute_item` |
| 8 | `ERROR` region at item level |
| 9 | Any other named item-level node |

Item flags:

| Bit | Meaning |
|---|---|
| 1 | `has_error` in the item's subtree |
| 2 | `mod_item` without a body (`mod x;`) |
| 4 | `function_signature_item` (no body) |

### 6.4 Parent decoding

The parent decodes strictly:

- `object_pairs_hook` refuses duplicate keys;
- each frame has exactly its key set;
- integers are exact `int` values with no `bool` or float, in [−1, 2³¹];
- `hello` comes first and `end` last, exactly once each;
- both nonces equal the invocation nonce;
- no byte follows `end`;
- the exit status is 0.

Every range must satisfy `0 <= s <= e <= n`. Items must nest:

- an item lies inside its parent item's range;
- name, visibility, self-type and trait ranges lie inside the item;
- attribute ranges are ordered, disjoint preceding siblings: after the end of
  the previous item in that scope and before this item's start, within the
  parent's range (or the full input for root siblings). They are not required
  to lie inside the declaration range;
- parent indices are smaller than the child's index;
- `end` counts equal the observed frames.

Any violation is a `protocol_violation`. The whole file is refused, recorded as
the receipt outcome `crashed` (failed clean-exit/protocol evidence), and never retried.
This classification does not attribute a cause to the parser itself.

### 6.5 Names and lines (`extractors/rust_pilot/observations.py`)

The parent computes names and lines from the retained input bytes:

- **Names.** Decode `bytes[s:e]` strictly as UTF-8. The text must be at most
  256 bytes and either satisfy `str.isidentifier()` or be `r#` followed by an
  identifier; the latter sets `raw_identifier`. A name failing this rejects
  only that item, recorded as `rust.unsupported` with `construct:
  name_rejected`.
- **Lines.** Build LF offsets once. `start_line = 1 + LFs before s`, and
  `end_line = 1 + LFs before max(s, e-1)`. CRLF counts once. Columns are not
  stored.
- **Text.** Visibility, impl self-type and trait text are decoded the same
  way, with whitespace runs collapsed. They are bounded to 32 and 256 bytes
  respectively, and set to `null` beyond that.
- **Attributes.** From each retained outer-attribute token, a bounded lexical
  prefix identifies `cfg`, `cfg_attr`, `derive` or `other`; nothing evaluates
  the attribute. Sibling association is checked before duplicate-name `@k`
  assignment, so cfg alternatives stay distinct. Comments are never included
  in unsupported counts.

## 7. Bounded stdio, deadlines and budgets (`extractors/rust_pilot/bounded_exec.py`)

Every exec runs as `subprocess.Popen` with argument lists, `close_fds=True`
and three pipes. The parent:

1. starts a stdout reader thread with its bound and a stderr reader thread
   bounded to 64 KiB **before** writing;
2. starts a writer thread that writes the stdin payload and closes stdin;
3. waits for the client to exit and both readers to reach end of file, against
   one monotonic deadline.

Overflow stops buffering, records the bound event, and triggers deadline
handling. Deadline handling does not just kill the client: it runs
`docker kill --signal KILL <id>`, then terminates and reaps the client and
joins the threads within the settlement budget. The parent never reads stdout
to completion before writing, and never writes all input before the readers
exist. A helper that writes before consuming its input therefore cannot
deadlock the parent.

| Budget | Bound |
|---|---|
| Construction (create, start, inspect, setup, readback) | 30 s per container; setup stdin ≤ 4 MiB; readback stdout ≤ 8 MiB |
| Probe execs (run level) | 10 s each; stdout ≤ 64 KiB |
| Parse | 5 s for the whole Docker exec, including startup/import; input ≤ 1 MiB; stdout ≤ 4 MiB; stderr ≤ 64 KiB |
| Settlement | 15 s per container |
| Container | memory 512 MiB (swap equal); 32 PIDs; tmpfs 16 MiB runtime and 4 MiB scratch; `nofile` 64; no core files |

Construction shares one absolute end across all nested clients and reaping.
Settlement starts once at the first bound event or normal settlement entry;
cost observation, final liveness inspection, kill, removal, absence queries
and client/thread cleanup share that same absolute 15-second end. A nested
call never obtains a fresh budget. Reader/writer failures and incomplete
stdin are not clean IO. A failed deadline action cannot skip client cleanup.

The parent additionally enforces depth 256, closed container parents, ordered
disjoint siblings, 4096-byte pointers and at most 16 MiB of retained raw Rust
semantics before expansion. A violation refuses the whole file's Rust claims
with `output_bound` at S4, preserving its legacy output.

Stderr bytes are never stored or echoed. Only their count, SHA-256 and a
categorical code survive. A successful parse with non-empty stderr is
recorded, as `diagnostic_present`. Overflow is `diagnostic_bound` and refuses
the file. Exit 137 with `OOMKilled` is `memory_bound`.

## 8. Settlement and residue

After every container, whatever the outcome, the parent:

1. runs `docker kill --signal KILL <id>` (not running is fine);
2. runs `docker rm -f -v <id>`;
3. polls `docker container ls -a --no-trunc --filter id=<id> -q` every
   250 ms until it returns empty, within the settlement budget.

The kill/removal exit is advisory because daemon AutoRemove can race it. A
successful, exact-ID absence query decides cleanup; a failed query, timeout
or remaining ID never proves absence.

Empty is **proven absence**. This polling is cleanup observation, not a retry
of the file. Unproven absence halts the run immediately, records
`cleanup_incomplete`, attempts no further file, and refuses every Rust claim
in the run.

At run start and end, the parent snapshots:

- `docker image ls -q --no-trunc`;
- `docker volume ls -q`;
- `docker container ls -a -q --filter label=org.repomap.rust-pilot.run=<run_id>`.

`process()` completes the end snapshot and its component attribution before
returning any admissible result. `verify_live()` and publication recheck this
settled state and exact owned-container absence. They cannot admit or publish
while that observation is pending. Every create/exec/cleanup command is held
in the run's closed command journal, and every container's exact image,
mounts and labels is checked. The journal has no image/volume creation,
build, pull or commit command; no guest sees a daemon socket. Pilot-owned
resource labels and inspected owned-container references must establish zero
new attributable images/volumes and an empty owned-container set. Missing or
ambiguous owned evidence refuses the run. This bounded pilot also requires
unchanged global image and volume sets as a conservative availability gate.
Unrelated additions or removals on a shared daemon can therefore refuse the
command; qualification requires a quiet daemon. Such a refusal spends the
attempt and supplies no retry or refund. No resource is pruned and no foreign
ID is removed. Builds and pulls attributable to the pilot must both be0.

## 9. Raw observations (schema 1)

Each Rust raw observation has these common fields:

- `extractor` is `rust-pilot-tree-sitter`;
- `extractor_version` is the RepoMap version;
- `confidence` is `extracted`;
- `path` and `source_id` are the repository-relative path;
- `metadata` includes `language: "rust"`,
  `dialect: "rust/tree-sitter-rust-0.24.2"`, `component_lock` and
  `selection_rule`.

The `language` and `dialect` values deliberately trip the ADR 0154 guard on
every non-witnessed path.

| Kind | Cardinality | Line range | Additional metadata |
|---|---|---|---|
| `rust.parse` | One per attempted file | 1 to the last line | `outcome`, `completeness` (`complete`, `partial`, `truncated`, `none`), `input_sha256`, `input_bytes`, `line_count`, `errors`, `missing`, `items`, `unsupported`, `item_list` (`complete`, `partial`, `macro_incomplete`), `build_script_name` |
| `rust.item` | One per accepted item | Item lines | `item_kind`, `namespace`, `pointer`, `parent_pointer`, `start_byte`, `end_byte`, `usable_scope`, `attributes` (`cfg`, `cfg_attr`, `derive` booleans; `other` count), `conditional`, `visibility`, `raw_identifier`, `body` (`inline` or `external_unresolved`, modules), `has_body` (functions), `self_type_text` and `trait_text` (impls), `member_list` (containers), `name_ambiguity` |
| `rust.unsupported` | One per (scope, construct) | First occurrence | `construct`, `count`, `scope_pointer` |

Item names occupy `RawObservation.name`; the canonical namespace is explicit
metadata. Function-body locals are unobserved rather than counted without a
body walk. Root item depth is 1; empty statements are trivia. Attribute-cap
overflow truncates the whole file's retained item list.
Under truncation, `attribute_list` is `truncated`; attribute flags describe
retained observations, and `conditional` is null if no retained cfg attribute
establishes it. Container membership cannot be complete under a truncated
stream. More specific error or macro incompleteness remains visible.

Outcomes for the `rust.parse` record and the receipt attempt:

| Pilot outcome | Receipt outcome | Completeness | Achieved |
|---|---|---|---|
| Complete tree (`root_error` 0, not truncated) | `succeeded` | `complete` | `syntax.tree` |
| Errors with at least one usable scope | `succeeded` | `partial` | `syntax.error_tolerant` |
| Truncated by a depth or node cap | `succeeded` | `truncated` | `syntax.error_tolerant` |
| Errors and no usable scope | `parse_rejected` | `none` | none |
| Time, output, memory, PID or diagnostic bound | `resource_bound_exceeded` | `none` | none |
| Protocol violation, nonzero exit, signal | `crashed` (failed clean-exit/protocol evidence) | `none` | none |

Pre-container refusals (§4, §5, §8) produce a receipt in state `refused`, with
code `dialect_unsupported`, `resource_bound_exceeded`, `inadmissible_effects`
or `witness_unavailable`, and no `rust.parse` observation. A missing profile
produces one run receipt in state `unavailable` with
`dependency_unavailable`. `file.classification` is a parent fact for every
selected path. It is never reported as a helper achievement.

## 10. Live witness (`extractors/rust_pilot/witness_state.py`, `controller.py`)

`RustPilotRun.open(...)` is a context manager. It owns:

- the run nonce, from `secrets.token_bytes(32)`;
- the verified prepared profile and its in-memory expected install tree;
- the observed runtime facts;
- the Docker client path and SDK image ID;
- per file: the retained input bytes and digest, the container ID, the parser
  and setup principals as specified and as guest-observed, exit status,
  output digest, decoded frames, resource events, absence proof and outcome;
- the resulting Rust raw observations.

Its rules:

- Nothing about it is serializable. `__reduce__`, `__copy__` and
  `__deepcopy__` raise.
- No module-level state exists.
- Leaving the context, or any `cleanup_incomplete`, makes the run inert.
- Before `process()` returns admissibly, all owned resources are settled and
  the run-wide residue check has completed. `verify_live()` recomputes that
  pre-publication condition; a still-open context alone grants nothing.

`ParentWitness` and `refuse_capability_admission` in
`extractors/contracts/witness.py` stay unchanged for legacy and offline
origins. The pilot reuses `REQUIRED_BINDINGS` as its checklist and records
each binding's recomputed result per file.

The witnessed canonicalizer recomputes all eight bindings (ADR 0155 D3) from
the run's own retained state immediately before admitting a file's
observations. Any failed binding refuses that file's Rust claims, and records
one diagnostic, `rust_pilot_binding_refused`, with the binding name.

## 11. Canonical vocabulary (`canonicalization/rust_pilot_family.py`, `graph/rust_keys.py`)

### 11.1 Namespaces

| Namespace | Segments | Built from |
|---|---|---|
| `rust.source_file` | 1 | file key |
| `rust.module` | 2 | file key, pointer (tag `mod`) |
| `rust.function` | 2 | file key, pointer (tag `fn`; signatures included, `has_body: false`) |
| `rust.type` | 2 | file key, pointer (tags `struct`, `enum`, `union`, `type`; `item_kind` metadata) |
| `rust.trait` | 2 | file key, pointer (tag `trait`) |
| `rust.impl` | 2 | file key, pointer (tag `impl`) |
| `rust.macro` | 2 | file key, pointer (tag `macro`; `macro_rules!` definitions only) |

The seven counts are additions to `graph/_key_namespaces._SEGMENT_COUNTS`.
`GRAPH_KEY_VERSION` stays 1, and `graph/keys.py` is unchanged.

### 11.2 Pointers

A pointer is `/` followed by `/`-joined steps:

- a named step is `<tag>:<name>`;
- an impl step is `impl:<n>`, where `n` is the 1-based ordinal among impls in
  that scope;
- a step gains a suffix `@<k>` (1-based, source order) when its scope holds
  more than one item with the same namespace and name.

All same-named siblings then carry `name_ambiguity: <count>`, and none is
preferred. Conditional (`cfg`) duplicates are therefore separate observed
alternatives, never resolved. Keys are percent-encoded by the existing
segment encoder and unique per file by construction. A duplicate key is a
defect that refuses the file.

### 11.3 Nodes, edges and evidence

Each node's metadata is a copy of its raw observation's descriptive metadata
from §9, plus `completeness_basis` (`complete_tree` or
`partial_tree_usable_scope`).

`rust.source_file` carries:

- `completeness` and `item_list`;
- the counts;
- `input_sha256`, `dialect`, `component_lock` and `selection_rule`;
- `build_script_name`.

Edges:

- `file:<path>` `contains` `rust.source_file:<path>`;
- `rust.source_file` `defines` each top-level item;
- `rust.module`, `rust.trait` and `rust.impl` `contains` each member.

Each node and edge links to its `rust.item` or `rust.parse` evidence with the
original raw ordinal. The legacy file node must already exist in the legacy
result; otherwise the file is refused.

### 11.4 Gating, completeness and unsupported constructs

The claim mapping is closed (ADR 0155 D5). A complete tree admits every
accepted item. A partial or truncated tree admits only usable scopes: the item
subtree has no error or missing flag, and its parent is the root or a usable
container.

A container whose own subtree has an error emits no members, and its
`member_list` is `error_incomplete`. Any item-position macro invocation sets
the scope's `member_list` (or the source file's `item_list`) to
`macro_incomplete`. `mod x;` yields a `rust.module` with
`body: external_unresolved` and no file edge.

Never emitted:

- call, import, use-target or impl-to-type edges;
- trait-implementation edges;
- `cfg` truth values;
- macro expansions;
- crate or module path resolution;
- package metadata;
- type facts.

## 12. Pipeline API, storage and readback

`extractors/rust_pilot/pilot.py` exposes:

```text
with RustPilotRun.open(docker_cli=..., sdk_image_id=..., profile_dir=...,
                       platform=..., audit_dir=...) as run:
    legacy = extract_observations_from_repository_files(root, file_infos)
    run.process(root, file_infos)
    witnessed = canonicalize_rust_pilot(run, legacy, repository_scope=...)
    publish_rust_pilot_generation(psql_args, witnessed, repository_name=...,
                                  root_path=...)        # optional
```

`canonicalize_rust_pilot` runs the unchanged `canonicalize_observations` on
`legacy`. It then appends the run's admitted Rust raw observations with
continuing ordinals. It builds Rust nodes, edges and evidence and returns a
`WitnessedCanonicalization`. That object:

- holds the merged result and the exact merged observation tuple;
- is non-copyable and constructible only by this function;
- is bound to the open run.

`storage/staged_rows.build_staged_rows` gains one keyword-only parameter,
`witnessed`. When supplied:

- it must be exactly that type;
- the `observations` argument must be its tuple;
- `verify_live()` must pass;
- it replaces recanonicalization.

Without it, behavior is unchanged.

The new `storage/staged_prepared_refresh.run_staged_prepared_refresh` admits
the prepared rows through the existing `_admit_and_run` and
`_run_staged_full_refresh_admitted(prepared_override=...)`. It uses direct
authority whose extractor contract adds `rust-pilot-lock-1`,
`rust-pilot-selection-v1` and the helper-closure digest
(`ops/rust_pilot_publication.py`). Readback uses existing canonical readback,
which accepts the new namespaces through `parse_key`.

Both generation identities are distinct from their default counterparts.
Let `H(x)` be SHA256 of sorted-key compact ASCII JSON. Derive
`extractor_generation = "eg1:" + H({"domain":"rust-pilot-extractor-v1",
"legacy":legacy_extractor_generation,"lock":lock_sha256,
"selection":"rust-pilot-selection-v1","helper":helper_closure_sha256})`.
Derive `canonicalizer_generation = "kg1:" + H({"domain":
"rust-pilot-canonicalizer-v1","legacy":legacy_canonicalizer_generation,
"family":"rust-pilot-family-v1","lock":lock_sha256,
"helper":helper_closure_sha256})`. Each suffix is64 lower-case hex digits,
within the existing staging-ownership generation pattern. No generation is
selected from a receipt. The native qualification import closure remains
dependency-free; publication/database owners are imported only at the
explicit PostgreSQL publication boundary, never by the AMD tool.

Refusal points:

| Path | Behavior |
|---|---|
| `canonicalize_observations` (offline raw JSONL, direct publication, `prepare_canonical_load`, replay of stored raw rows) | Claim guard reason `rust_raw_kind` for `rust.parse`, `rust.item` and `rust.unsupported`, before dispatch, plus the existing Rust language assertion. Precedence: receipt reference, capability metadata, `rust_raw_kind`, then the language assertion |
| Portable worker | Never imports `extractors.rust_pilot`; enforced by an import-boundary unit owner |
| Parent bundle validation (`artifacts/validator.py`) | Refuses `rust.*` raw kinds and canonical namespaces in worker bundles |
| Receipts, run reports, sidecars | Audit only. Decoding can express only `unverified` or `refused`, and nothing reads them to select or admit |
| `build_staged_rows(witnessed=...)` after the run closed | Refuses |
| SQLite Local | Not reachable; requires a portable receipt (ADR 0155 D2) |
| Multi-source pipeline | Not reachable in the pilot |

The ADR 0154 foundation specification's sentence that "unsupported kinds such
as `rust.function` keep `unsupported_raw_observation_kind`" is updated by the
source milestone. It changes for the three pilot kinds only.

## 13. Receipts, reports and retention (`extractors/rust_pilot/receipts.py`)

There is one `cloe-extractor-run-receipt-v1` per container invocation, with one
attempt:

- `producer` is `rust-pilot-helper`;
- `consumer_boundary` is `rust-pilot-parent-v1`;
- `run_id` is `<run_id>.<seq>`;
- `source_sha256` is the input digest.

Declared:

- stage `S3`;
- `language_dialect` `rust/tree-sitter-rust-0.24.2`;
- `runtime_identity` `cpython-3.13.12`;
- capabilities `["syntax.error_tolerant", "syntax.tree"]`;
- effects `none`, `subprocess`, `selected-input`, `scratch`, `none`;
- provenance `python-distribution`;
- invocation mode `container-exec-v1`;
- `dependency_sha256` = lock digest;
- `profile_sha256`.

Observed:

- installed and admitted facts;
- `artifact_sha256`, the parent-computed digest of the read-back install tree;
- the attempt, resource events and exit status;
- `cleanup` (`proven` or `incomplete`);
- `verification` `unverified`. A serialized receipt cannot carry success.

D3 admission per effect dimension:

| Dimension | How admission is established |
|---|---|
| Network | Enforced (`none`) |
| Read scope | Enforced: no mounts; input arrives on stdin only |
| Write scope | Enforced: read-only root, sealed prefix, `noexec` scratch |
| Target code | Witnessed: no toolchain is invoked; the helper is parse-only |
| Boundary | Enforced: subprocess container |

A run report, schema `cloe-rust-pilot-run-report-v1`, records:

- platform, SDK image ID and Docker server facts;
- observed runtime facts;
- the lock, profile and helper-closure digests;
- per-file categorical outcomes keyed by input digest, construction/readback/
  parse/settlement milliseconds and installed/readback/output byte counts;
- guest-reported memory peak when available, otherwise null with a reason;
  construction includes readback and the report states that nesting;
- counts and phase timings;
- residue snapshots as equality results;
- receipt digests.

The successful run-level probe parse receives a distinct `.probe` receipt
identity. Containment-only invocations have component records and no invented
extractor capability. The public controller accepts no runner, verifier,
clock or sleep callbacks; its audit accessor returns only deep inert copies.
Witnessed canonicalization rechecks live admission and guards its exposed
raw/result content against mutation immediately before publication.

Paths appear only for public fixtures. Receipts and reports are stored with
ADR 0154 bounded IO in a caller-owned private `0700` directory. They are
retained for audit and never consulted for admission, selection or replay.

## 14. Qualification window

### 14.1 Manifest and frozen inputs

`tools/ci/rust_pilot_qualification_manifest.json`, schema
`cloe-rust-pilot-qualification-manifest-v1`, binds:

- the current window ID `RUST-PILOT-QW2` (the approved replacement of failed window1);
- the lock digest;
- the per-CPU profile digests;
- the helper-closure digests: setup writer, install readback, runtime probe,
  parse helper, containment probes and probe source;
- the fixture and gold digests;
- the scenario IDs and expected outcomes;
- the attempt identities;
- the stopping rule: one execution of the command over the whole manifest;
- the replacement policy: none.

The candidate is the commit that contains the manifest. Execution refuses when
any bound digest differs from the checkout.

`source_checkpoint` identifies the published main ancestor before this
manifest existed; it does not assert that ancestor contains the pilot.
Current candidate source identity is the complete `closure.python_digests`
list of closed `{path, sha256}` records plus the positive sealed D12
candidate SHA/tree. Each source path occurs exactly once; both path and
digest retain their ordinary public text representation. The main parent is
available in the existing two-generation merge checkout; no history fetch
or checkout policy change is needed for this historical ancestry check.

Fixtures live in `src/test/fixtures/rust_pilot/`: at least10 original,
RepoMap-authored varied public Rust files, with no copied third-party code or
line-count filler. The long-position scenario exceeds300 rows and columns;
other fixture size is driven by the scenario and claim sample. Golds live
in `src/test/fixtures/rust_pilot/golds/`,
schema `cloe-rust-pilot-gold-v1`. Each gold lists every expected item
(namespace, pointer, name, `item_kind`, lines, bytes, `usable_scope`) and the
expected completeness and unsupported counts, together with the probe gold.

Fixtures and golds are committed and bound before the first native execution,
and are never tuned afterwards. A changed fixture or gold is a new window.
Every window shares the same ARM budget.

The operator explicitly approved window2 after the frozen window1 native run
found one exclusive endpoint mismatch. Only the unfinished module's
`end_byte` in `q04_missing_brace.gold.json` changes253→252; all13 source
fixtures, the other12 golds and420 claims are preserved. Window1 stays failed
and immutable. This is a declared replacement window, not a tuned pass for
window1, and it adds no ARM attempt. Test-only EOF recovery follows the observed
native span; production helper offsets remain unmodified.

The comparator retains actual and expected canonical documents for every
compared public fixture, together with closed mismatch field names and hashes.
It accumulates mismatches instead of stopping at the first, then refuses the
command if any exist. The compact comparison collection is capped at768KiB,
reserving256KiB of the unchanged1MiB AMD report envelope for other evidence.
Collection overflow marks evidence incomplete and refuses. If the complete
report still exceeds1MiB, retain a bounded failed report with unknown counters
and the omitted report digest, then fail the command; never discard its report.
These reports contain only the manifest-bound public fixture comparison;
no arbitrary runtime text, wheel payloads or private repository input is added.

After a complete comparison, a later measurement, graph, accounting, deadline
or cleanup refusal retains that document set as `completed_gold`, including
the public CLI and private ARM post-adapter failure handlers. It remains a
failed command, never native qualification. A bounded whole-report fallback
can retain only its omitted-report digest; this diagnostic limit is explicit.

### 14.2 Scenarios

| ID | Scenario | Tier |
|---|---|---|
| Q01 | All item tags, nested modules, impls and traits, `macro_rules!`, complete tree | T1 + T2 |
| Q02 | More than 256 lines and an item name past column 256; the run-level probe adds a line over 300 | T1 + T2 |
| Q03 | UTF-8 identifiers, raw identifiers, CRLF, BOM | T1 + T2 |
| Q04 | Malformed source with usable and unusable scopes, missing braces, truncation | T1 + T2 |
| Q05 | `cfg` duplicates, `cfg_attr`, `derive`, item macros, `mod x;`, inner attributes, `build.rs` | T1 + T2 |
| Q06 | Invalid UTF-8; input over 1 MiB | T1 + T2 (refused before the container) |
| Q07 | Missing, extra-entry, wrong-digest and wrong-CPU profile | T1 + T2 (missing profile is the default no-acquisition run) |
| Q08 | Bad ranges, nesting, names, nonce, duplicate keys, unknown keys, floats, extra bytes | T1 only |
| Q09 | Output, stderr and time overflow; crash; OOM; cleanup failure; residue | T1 fakes + T2 containment probes |
| Q10 | Wheel tamper: traversal, symlink, `.pth`, entry points, `RECORD` mismatch, extra or conflicting distribution | T1 (host verifier and writer) + T2 (one tampered setup frame refused in a container) |
| Q11 | Cross-platform refusal: `aarch64` profile against an `amd64` server and the reverse, non-Linux server, interpreter, ABI or glibc mismatch | T1 + T2 (the ARM run requests the `x86_64` profile and must refuse before construction) |
| Q12 | Legacy invariance: default and pilot runs give byte-identical legacy family rows | T1 + T2 |
| Q13 | Witnessed canonicalization to staged rows, PostgreSQL publication and readback | T1 (integration, fake protocol) |
| Q14 | Offline raw, worker bundle, closed run, copied or pickled witness all refused | T1 |

The manifest freezes an explicit subset for each attempt. ARM runs Q01–Q07,
Q09–Q12 with the native/probe portions only, and uses the already acquired
x86_64 pair for Q07/Q11 CPU refusal. AMD runs Q01–Q06, the missing/tampered
native-pair parts of Q07, and Q09/Q10/Q12. No AMD Q11 negative scenario is selected. Positive native platform,
interpreter/ABI/glibc checks do not qualify mismatch cases, and no ARM pair is
prepared or downloaded. It does not claim the ARM-profile-on-AMD case. Q08/Q13/Q14 remain scoped T1 evidence on either platform. No AMD
scenario may require a seventh transfer or an unavailable ARM artifact.

T1 behavioral tests may import the RepoMap-owned guest Python modules to
exercise their framing, archive and retained-byte logic with pure Python
stand-ins. Their module initialization imports only the standard library;
the tests must intercept or refuse every native-package import. Test-owned
normalizations and interpreter state are restored after each invocation.
This permits direct source coverage without changing its denominator, and
proves neither native runtime behavior nor containment. The product and native
qualifier continue to read guest programs as text payloads, except for the
inert guest package initializer used by resource lookup.

T2 containment probes (`guest/containment_probes.py`) are RepoMap-owned stdlib
probes, each run as the parser UID in its own fresh container. Each one must
observe its expected refusal:

- TCP and UDP sockets to a non-loopback address;
- writes to `/`, `/opt/repomap-rust` and its files;
- `chmod` of the sealed tree;
- executing a file written to `/scratch`;
- `setuid(0)`;
- reading `/var/run/docker.sock` (absent);
- 40 processes or threads against the 32 PID limit;
- allocating 600 MiB against 512 MiB;
- sleeping past the 5 s deadline;
- writing 5 MiB to stdout and 100 KiB to stderr;
- `os.abort()`.

The parent requires the matching outcome and proven absence for each.

### 14.3 Acceptance and accounting

A component attempt passes only when all of the following hold:

- every T2 scenario matches;
- the probe gold matches;
- the false-positive count is 0 over the exhaustive sample of every emitted
  item claim (at least 150 expected): any emitted claim whose namespace,
  pointer, name, kind, lines or bytes are not in the gold is a false positive;
- recall is 100% for complete-tree fixtures;
- every partial-tree item gold-marked usable is emitted;
- all containment probes refuse as expected;
- absence is proven for every container;
- image, volume and label residue is zero, with builds and pulls at 0;
- every budget held;
- the report validates.

Cost accounting is recorded per file and in total:

- construction, readback, parse and settlement milliseconds;
- readback bytes;
- installed tree bytes;
- guest-observed `memory.peak` (labelled guest-reported);
- output bytes.

It is compared with the incumbent run on the same fixtures: legacy discovery
time, one `unknown` file node per `.rs` file, and zero items. Report yields as
items per file, and ambiguous, unsupported and partial counts.

Measurements are `[measured fact]` for that attempt and platform only. No
performance-based adoption claim is made, and no claim is made about `syn` or
rust-analyzer. Five curated navigation tasks over the fixtures (locate a
named function, trait, impl, macro and module) report answerable with the
pilot versus the incumbent, as a graph-quality delta. They are not a product
claim.

### 14.4 Attempts

| Attempt | Where | Allowed |
|---|---|---|
| `RP-ARM-1` | Docker Desktop native `linux/aarch64`, retained SDK image `575e0004…` (full ID from private custody, equal to `docker image inspect`), aarch64 profile from the four inert transfers | Once, after G1–G4 |
| `RP-ARM-2` | Same | Only after an `RP-ARM-1` finding, its correction and a fresh source review; last ARM execution |
| `RP-AMD-1` | Existing `d12-native-amd64` job (§15) | Once, in the next separately granted substantial public campaign |

Each attempt is declared before execution with all six qualification-evidence
fields. Every execution is recorded, including failures. A later pass does not
erase an earlier failure. There is no local emulation and no SDK, application
or runtime-image build.

## 15. AMD gate: exact workflow delta

Insert these two steps after `Upload native D12 qualification evidence` in
`d12-native-amd64`, identically in `tools/ci/d12_native_amd64_job.yml`:

```yaml
      - name: Run Rust parser component qualification
        if: always()
        run: |
          python3 tools/ci/rust_pilot_qualification.py amd64 \
            --repo-root "${GITHUB_WORKSPACE}" \
            --d12-state-dir "${RUNNER_TEMP}/d12-native-amd64-evidence" \
            --d12-sealed-json "${RUNNER_TEMP}/d12-native-amd64-evidence/d12-native-amd64-sealed-evidence.json" \
            --manifest "${GITHUB_WORKSPACE}/tools/ci/rust_pilot_qualification_manifest.json" \
            --work-dir "${RUNNER_TEMP}/rust-pilot-amd64-work" \
            --report-dir "${RUNNER_TEMP}/rust-pilot-amd64-report"

      - name: Upload Rust parser component evidence
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: repomap-rust-pilot-amd64-${{ github.run_id }}-a${{ github.run_attempt }}-${{ github.sha }}
          path: ${{ runner.temp }}/rust-pilot-amd64-report
          if-no-files-found: error
          retention-days: 14
```

`amd64` works in this order:

1. **Prerequisites.** The command validates, in order:
   - the sealed D12 JSON, through `validate_sealed_d12_evidence` with positive
     qualification required: `result == "passed"` and `qualified is true`;
   - candidate SHA equality with the checkout;
   - the exact `sdk_image_id` recorded by D12 `prepare`;
   - `docker image inspect` reporting that ID, `linux` and `amd64`.

   Any failure writes `rust-pilot-qualification.json` with
   `result: "prerequisite-refused"`, `qualified: false` and a reason code, then exits 1
   with zero downloads, constructions and parses.
2. **Acquisition.** The command downloads the two `x86_64` URLs with
   `urllib.request`. Each download has a size cap of the locked size, a
   SHA-256 check and an exclusive write into `--work-dir`. These are the two
   remaining permitted transfers; no third fetch or fallback is attempted.
   Failure means `result: "failed"`, a closed acquisition reason and exit 1.
3. **Prepare and run.** It runs `prepare` (§3), then the manifest's T2
   scenarios (§14). It writes the run report, the receipts and
   `rust-pilot-qualification.json`, then exits 0 only on a component pass.
   A separate `rust-pilot-attempt-intent.json` records invocation, never success.

The command shares one monotonic20-minute work deadline across its phases;
expiry refuses new work and qualification while preserving the existing bounded
cleanup obligation. No nested phase resets it or enlarges a per-operation cap.
The job timeout is unchanged. This is a cooperative work
window, not an OS hard wall: an already active bounded operation may finish
after expiry, followed by exact settlement. No new phase, container, exec or
transfer begins after an observed expiry, and qualification always refuses. It imports only the stdlib and the dependency-free pilot closure.
Neither `psycopg`, `storage.staged_ingestion`, `storage.staged_prepared_refresh`
nor the PostgreSQL publication owner is imported. A subprocess import-boundary
unit test blocks those names and proves the command can still load.

`qualification_native_contracts.py::validate_d12_native_amd64_job` owns the
existing D12 checks, including exactly one D12 artifact upload. Narrow that
upload selector to identify the existing D12 upload, retaining every D12
condition and ordering check. A new small `qualification_rust_contracts.py`
owner enforces exactly two total uploads and exactly the two permitted Rust
steps; rejects extra, missing, duplicated or weakened steps; and asserts:

- the two steps, in that position;
- `if: always()` on both;
- no `continue-on-error`;
- the unchanged job, runner, timeout, permissions and triggers;
- projection equality.

## 16. Implementation owners and exact selectors

### 16.1 New product modules

Each is at most 400 lines and enters type ownership and retention as a clean
`python_retained` addition. No new test dependency, suppression, core
metadata, lock or runner policy is added.

| Module | Role |
|---|---|
| `extractors/rust_pilot/__init__.py` | Imports nothing native |
| `extractors/rust_pilot/component_lock.py` | §2 |
| `extractors/rust_pilot/archive_verifier.py` | §2.2; in-memory expected install tree |
| `extractors/rust_pilot/prepared_profile.py` | §3 |
| `extractors/rust_pilot/selection.py` | §4 |
| `extractors/rust_pilot/docker_boundary.py` | §5.1, §5.2, §8; argument builder, inspect, kill, rm, absence, residue |
| `extractors/rust_pilot/construction.py` | §5.3–§5.6 |
| `extractors/rust_pilot/probe_material.py` | §5.6 probe source and gold constants |
| `extractors/rust_pilot/bounded_exec.py` | §7 |
| `extractors/rust_pilot/helper_protocol.py` | §6.1, §6.3, §6.4 |
| `extractors/rust_pilot/observations.py` | §6.5, §9 |
| `extractors/rust_pilot/witness_state.py` | §10 |
| `extractors/rust_pilot/controller.py` | §10 |
| `extractors/rust_pilot/receipts.py` | §13 |
| `extractors/rust_pilot/pilot.py` | §12 |
| `canonicalization/rust_pilot_family.py` | §11; `WitnessedCanonicalization` |
| `graph/rust_keys.py` | §11.1, §11.2 |
| `storage/staged_prepared_refresh.py` | §12 |
| `ops/rust_pilot_publication.py` | §12 |

`extractors/rust_pilot/probe_material.py` is a host module holding the §5.6
probe source and its gold as constants.

The `extractors/rust_pilot/guest/` package holds stdlib-only Python 3.13
text: `__init__.py`, `setup_writer.py`, `install_readback.py`,
`runtime_probe.py`, `parse_helper.py` and `containment_probes.py`.

The guest modules are loaded as text through `importlib.resources`. They are
never imported by host modules, and have no module-level side effects.
`parse_helper.py` reaches the pair only through its one `importlib.import_module`
site, so mypy needs no missing-import suppression. Any dynamic-import
admission row the retention dependency tooling requires is a clean addition.

`guest/__init__.py` makes the existing `packages.find` configuration ship the
guest files as package modules. The notice files fall under the existing
`third_party_licenses` package-data patterns. No `pyproject.toml`, core
metadata or lock change is needed.

### 16.2 Narrow existing edits

- **`canonicalization/claim_guard.py`:** reason `rust_raw_kind`.
- **`canonicalization/main.py`:** unchanged.
- **`graph/_key_namespaces.py`:** seven entries.
- **`graph/keys.py`:** unchanged.
- **`storage/staged_rows.py`:** the keyword-only `witnessed` parameter, with
  about 10 lines.
- **`artifacts/validator.py`:** worker-bundle Rust refusal, delegated to a new
  small helper if needed. `_bundle_stream_parse.py` is unchanged.
- **`third_party_licenses/`:** the two records of §2.3.
- **`.github/workflows/repomap-release-qualification.yml`** and
  **`tools/ci/d12_native_amd64_job.yml`:** §15.
- **`tools/ci/ci_topology.py`:** the §15 assertions.
- **`tools/ci/qualification_native_contracts.py`:** narrowly identify the D12
  upload and delegate the additional closed Rust contract without growing
  this400-line owner or weakening D12 checks.
- **New `tools/ci/qualification_rust_contracts.py`:** §15 assertions.
- **New tool `tools/ci/rust_pilot_qualification.py`** (≤ 400 lines; helpers in
  `tools/ci/qualification_rust_*.py`): the public command exposes `amd64` only.
  Bounded native ARM qualification uses the parent-held private wrapper that
  invokes `run_native_component`; there is no public `local` subcommand.
- **`tools/ci/rust_pilot_qualification_manifest.json`**, plus a fixture
  authority or public-fixture manifest row if those registries govern
  `src/test/fixtures/rust_pilot/`.
- **`docs/specs/cloe-extractor-capability-foundation-v1.md`:** the §12
  sentence.
- **Retention files:** clean rows in `tools/ci/python_type_ownership.json` and
  the retention inventory. Every existing row, debt ceiling, scope registry and
  tool profile is preserved.

### 16.3 Unit selectors

These are T1 tests: no Docker, no wheel and no native import. Each selector
has the prefix `src/test/unit/python/repomap_kg/extractors/rust_pilot/`:

- `component_lock.unit.test.py`
- `archive_verifier.unit.test.py`
- `prepared_profile.unit.test.py`
- `selection.unit.test.py`
- `docker_boundary.unit.test.py`, covering the exact argument vector and
  inspect, absence and residue logic with an injected command runner
- `bounded_exec.unit.test.py`, using real stdlib child processes for
  overflow, timeout and deadlock ordering
- `helper_protocol.unit.test.py`
- `observations.unit.test.py`
- `guest_setup_writer.unit.test.py`, running the writer source in a host
  subprocess against temporary directories and synthetic archives
- `guest_source_guards.unit.test.py`, the §6.2 AST guard plus the guest
  stdlib-only and no-host-import checks
- `witness_state.unit.test.py`
- `controller.unit.test.py`
- `receipts.unit.test.py`
- `pilot_routing.unit.test.py`, covering default `.rs` output invariance, core
  import with `tree_sitter` blocked, and the portable-worker import boundary

Further unit selectors:

- `src/test/unit/python/repomap_kg/canonicalization/rust_pilot_family.unit.test.py`
- `src/test/unit/python/repomap_kg/graph/rust_keys.unit.test.py`
- `src/test/unit/python/repomap_kg/extractors/contracts/witness_claim_guard.unit.test.py`
  (updated)
- `src/test/unit/python/repomap_kg/artifacts/bundle_receipt_validator.unit.test.py`
  (updated)
- `src/test/unit/python/tools/ci/ci_topology.unit.test.py` (updated)
- `src/test/unit/python/tools/ci/qualification_native_contracts.unit.test.py`
  and `src/test/unit/python/tools/ci/d12_native_python_job.unit.test.py`
  (updated for the closed D12+Rust contract)
- `src/test/unit/python/tools/ci/qualification_rust_contracts.unit.test.py`
- `src/test/unit/python/tools/ci/rust_pilot_qualification.unit.test.py`
- `src/test/unit/python/repomap_kg/architecture/arch1d_dependency_dag.unit.test.py`
  and `src/test/unit/python/repomap_kg/extractors/package_structure.unit.test.py`
  (updated if their closed lists require it)

### 16.4 Integration selectors

These run in the containerized sandbox with `--pg-container-port 55433` and
`--no-coverage`:

- `src/test/int/python/repomap_kg/extractors/rust_pilot/pilot_storage_readback.int.test.py`
  (T1). It runs the real guest `parse_helper.py` in a host subprocess against
  a test-support stdlib stand-in for the two packages. The stand-in lives in
  `src/test/support/python/repomap_test_support/rust_pilot_fake_tree_sitter/`.
  The boundary factory is replaced through test support, which is the trusted
  in-process limit. The run goes through real validation, witnessed
  canonicalization, staged rows, PostgreSQL direct publication and canonical
  readback. It asserts that legacy rows are unchanged.
- `src/test/int/python/repomap_kg/extractors/contracts/canonical_claim_refusal.int.test.py`
  (updated). Offline raw `rust.*` kinds are refused.
- `src/test/int/python/repomap_kg/extractors/rust_pilot/container_boundary.int.test.py`.
  It exercises real create, exec, kill and absence on the inner daemon with a
  stdlib fake helper, only with an image already admitted there. With no such
  image, this is a named gap for parent disposition. No image is pulled or
  built.

Complete local suites, coverage, builds and SDK or application images remain
unselected.

## 17. Disable and rollback

No prepared profile means no acquisition, one `dependency_unavailable`
outcome, and no container or Rust claim. Not calling the pilot API means
default behavior is unchanged. Removing the source milestone removes:

- the claim-guard reason, namespaces, modules and workflow steps;
- every stored pilot generation, which the next default publication
  supersedes.

No data migration exists.

## 18. Trust and containment limits

- **Parent trust.** The in-process parent, RepoMap source, the host Docker
  daemon, same-UID processes and privileged host processes are trusted. A
  monkeypatching parent can forge claims, and no claim is made against that.
- **Guest reports.** Guest-reported facts (credentials, mounts,
  `memory.peak`, interpreter facts) are labelled. The parent cross-checks
  them with host inspection where possible.
- **Supply chain.** Trust is exact digests only. There is no publisher
  attestation (all provenance requests returned 404) and no source-to-wheel
  reproduction.
- **Compromise containment.** Parser compromise is contained, not prevented:
  no network, a read-only root, a sealed prefix, dropped capabilities, no
  new privileges, and memory, PID and time bounds. Image tools (for example
  `gcc` and `go` in the SDK image) are reachable by a compromised parser, but
  it cannot persist, write the prefix or exfiltrate.
- **Platform evidence.** Docker Desktop's guest kernel is not bare-metal
  Linux. ARM evidence says nothing about host macOS without containers.
- **Defect avoidance.** Avoiding the `Point` API addresses known defect 472
  only. It is not a general memory-safety argument.
- **Operating systems.** Windows, macOS, non-glibc and other interpreters are
  refused, not supported.

## 19. Gates

| Gate | Requirement | State |
|---|---|---|
| G1 | Bundled-notice review: the wheels' extensions and core commit `7f5348…`, including any third-party code vendored inside the core tree; core notice text committed | pending |
| G2 | AGPL-3.0-or-later outbound review recorded: no redistribution of wheels or of the constructed runtime; notices retained; no legal conclusion asserted | pending |
| G3 | ADR0155 accepted after independent design review and parent F1–F8 corrections | accepted for implementation; no native acceptance |
| G4 | Source milestone and T1 owners green; independent source and mechanism review | pending |
| G5 | `RP-ARM-1` (and `RP-ARM-2` only if needed) passes §14.3 | pending |
| G6 | `RP-AMD-1` passes in a separately granted campaign | pending |
| — | W6 closure, ADR 0071 comparison, container-free Local Rust, production, v0.1.0 | out of scope |

## 20. What would make this contract wrong

- A `rust.*` claim is stored or read back without all eight bindings
  recomputed from an open run.
- Any non-witnessed path admits a Rust kind or namespace.
- The default or pilot run changes a legacy row.
- A parse sends or receives a target byte before construction readback passes.
- A root exec occurs after sealing.
- A host path, socket or volume is mounted.
- Any helper source uses a forbidden API (§6.2), or parses twice.
- A container lacks proven absence, or the run leaves an image, volume or
  labelled residue.
- Indexing reacquires, resolves or builds a dependency.
- The AMD command downloads, constructs or parses after a refused D12
  prerequisite.

## Bounded pilot evidence limitations

The captured source-controller command count is a snapshot through its audit
point. Later read-only live-witness and canonicalization queries, and the
three separate AMD SDK-prerequisite queries, are outside the aggregate. The
reported command totals are therefore captured-role counts, not end-to-end
invocation totals or a basis for performance or adoption claims. The closed
verb allowlist and separate zero-build, zero-pull and residue gates remain
mandatory.

The shared 20-minute window is cooperative. A read-only comparison phase can
overrun it within existing per-call caps; cleanup and observation remain
available. A final cutoff check refuses successful qualification after expiry.
Expiry in containment or a preflight can produce a generic containment code
or incomplete role evidence. Pre-attempt expiry can write an effects-refusal
row while the enclosing command reports the deadline. These diagnostic limits
confer no native credit: incomplete or refused evidence remains unqualified.

Gold binding relies on prior manifest validation and committed-source or
parent-wrapper byte checks, without a fresh hash at every comparison read.
This retains the same-user trust boundary. An interrupted oversized-input
probe can leave its public synthetic source in the audit upload root; wheel
payloads remain confined to separate private scratch.
