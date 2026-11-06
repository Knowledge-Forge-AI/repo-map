"""Stdlib-only Route B one-use D12 system build grant and host admission proof contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from ci.d12_system_grant_io import (
    D12SystemGrantError as D12SystemGrantError,
    is_strict_int as _is_strict_int,
    is_hex32 as _is_hex32,
    is_hex40 as _is_hex40,
    is_hex64 as _is_hex64,
    loads_strict_json_object as loads_strict_json_object,
    read_regular_json_object as read_regular_json_object,
)

from common_lore_index.runtime.release import PRODUCT_MINIMUM_LIBPQ_VERSION
from common_lore_index.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST

SYSTEM_BUILD_GRANT_SCHEMA = "repomap-d12-system-build-grant-v1"
SYSTEM_ADMISSION_PROOF_SCHEMA = "repomap-d12-system-admission-proof-v1"
EXPECTED_PHASE_ID = 'REPOMAP-CLOE-RESOURCE-EXPERIENCE1'
EXPECTED_WORKFLOW_PATH = ".github/workflows/repomap-release-qualification.yml"
EXPECTED_SYSTEM_OWNER, EXPECTED_REPOSITORY = "main-system-gate", "Knowledge-Forge-AI/repo-map"
EXPECTED_BEFORE_SHA = '4c61936725ed711cc0fe655eec143d90ea5f6143'
EXPECTED_BASE_SHA = "5ad00d162ad8a04430874275246a53227578c533"
EXPECTED_APPROVAL_SHA256 = '6fd1720b6272722011a63b3538f6fbb55f2943fa8f51bbb440a1d518b7291592'
EXPECTED_LEDGER_BEFORE_SHA256 = 'd896867aa70ca54030d855a5df71f6289f16272a61c20b3af7b535847c3a52f5'
SPENT_CI69_NONCE = "68920c8be2054bddaefba6ff1761b2e5"
SPENT_CI69_RESERVATION_SHA256 = "60d67477702e81125b5fba737c182965a78bcb6865c4e267adb0d064a71ac595"
SPENT_CI70_NONCE = "2ca8d5a3ad7645798437728db064e8d4"
SPENT_CI70_RESERVATION_SHA256 = "aba49e31a10db6bb6326e48f0fd681ede763e3be0fa86f37ddda1bae0df76a91"
SPENT_CI71_NONCE = "549ee11fd8a44b4f8723030412032fa3"
SPENT_CI71_RESERVATION_SHA256 = "159885801ce51461100eaf345163f02fb2b7ebc91eef71ff146acac66bc131be"
SPENT_CI72_NONCE = "1e9709f9ba0d46b28064fe7b0f9b3cbb"
SPENT_CI72_RESERVATION_SHA256 = "c0072c52ae05239180452e7b37b2d76ddf4ee78811facfa3cc00aa2ed2e3b692"
SPENT_CI85_NONCE = "e2833d583de847a7859fb5250d5f37c6"
SPENT_CI85_RESERVATION_SHA256 = "04c66536b5f655be479934d1086bec6895ac9015bdcf3da96c197a7f9d28bc4f"
SPENT_CI86_NONCE = "3777470657bc4361b42b3e4de8ba8586"
SPENT_CI86_RESERVATION_SHA256 = "dfa6d5670c156ce86a43fb45edf59d6f432bad71f11c139a09b2de864c6e5ba6"
SPENT_CI87_NONCE = "8f2ad7e4086946c9818c8ba1bad4c4f7"
SPENT_CI87_RESERVATION_SHA256 = "ac70c59663ff37177c5e072066d38d93d09caf7aca1aa8b0e90074dfaa849273"
SPENT_CI91_NONCE = "60454e3a42db44d697f22e2d9654c1ba"
SPENT_CI91_RESERVATION_SHA256 = "8e43691e6a1e36030ceee05dcee444cfcd2b97005ff535e61f3cfcd4b235badf"
SPENT_CI92_NONCE = "ba621a38a1f74b6296f9d29bb703aeac"
SPENT_CI92_RESERVATION_SHA256 = "d3beeb1e8c29d47d05730786772f2a2807fa89b934ca315d96737860f921436d"
SPENT_CI93_NONCE = "4f57c05c6efd46d486c2cf948611ad30"
SPENT_CI93_RESERVATION_SHA256 = "955ea803325ac5486092824740c6c648146b4a110e6dcd447272d09f1773bd11"
SPENT_CI94_NONCE = "57a15c277787496bbfdaca7d8e47b439"
SPENT_CI94_RESERVATION_SHA256 = "99b66797facf70177b057a644d74d9b9214b49bde2fbaee89ef680552ada244e"
SPENT_CI95_NONCE = "d4ea67e655f54742ac8ddc6a06174acf"
SPENT_CI95_RESERVATION_SHA256 = "ea75f3855f0e1fdb0246e8850511a8ec227d173b614f885401183f7db1a8f85e"
SPENT_CI96_NONCE = "8cf0db5228e2467b991ff5a0a2eba5ea"
SPENT_CI96_RESERVATION_SHA256 = "9564f2cd46bb25aca763c3ab9e7bf321ec0a9e2d043283f57cbf2d3147812498"
SPENT_CI97_NONCE = "a3b8757061cd4f1881b2d2bf96340539"
SPENT_CI97_RESERVATION_SHA256 = "62a1f0359398652f8e2524f468f61763eda84d6d20fba52c58bc941c16e78192"
SPENT_CI98_NONCE = "d20a514d6d3144edb9f1408d55cfd408"
SPENT_CI98_RESERVATION_SHA256 = "60a7a3a141d49c4fb0cf9a440afb9fb7c7215b4b523cc2841ea5bd518c802fd7"
SPENT_CI99_NONCE = "9fbd0f97ac4945a4a3bc231cbc512b5f"
SPENT_CI99_RESERVATION_SHA256 = "dfe02b643a6dafc7161d37b841ab97e9dbf34a6bf0f9dcc41c91e9c2a855f65e"
SPENT_CI100_NONCE = "10f975ff610e4030bd68cc09eba9d53b"
SPENT_CI100_RESERVATION_SHA256 = "12fad920fef49dc9604bbc4c69108fcf7867503787244b6bfd85feac66836e68"
SPENT_CI101_NONCE = "0e28d22b081149c7a4c7b0bab21fa1ef"
SPENT_CI101_RESERVATION_SHA256 = "3b5f2e8514e4b151794bba31c70b1e2b93f029ddba0fd2c9a1ab38f6e6ecd47c"
SPENT_CI102_NONCE = "7efd4e22bf9fb53df4eda303f1be9339"
SPENT_CI102_RESERVATION_SHA256 = "8fe5f174b333654f980b9561c93f2c5523e644674f72e321793eaf6f28abcdce"
SPENT_CI103_NONCE = "d0d625000a771536cc0dee3af1c3e650"
SPENT_CI103_RESERVATION_SHA256 = "674777fcea298e88f4bc48bd95ec1a7fa91c449ed6e61d827fe947e8dd34bf02"
SPENT_CI104_NONCE = "a39bf353e1d68d49a7d545986e163a1f"
SPENT_CI104_RESERVATION_SHA256 = "1e25a69b113f8c045a5ffaf678b94d6f639cc722817cad573af3c058b27e130a"
SPENT_CI105_NONCE = "8b763cc4281fb2aa0695a1e3a0274b83"
SPENT_CI105_RESERVATION_SHA256 = "4f45d2debccc74998cceccb070278eb5d097cdd082b5722125b8835b65945187"
SPENT_CI106_NONCE = "cefe2333256878de7307757db244fa0d"
SPENT_CI106_RESERVATION_SHA256 = "a9fced34e268438b0de90d1070e2fc2d199f8ced002f45b6e122e3918da7ba35"
SPENT_CI107_NONCE = "674dcffdf793d911ce7fb1c3ab2b90ca"
SPENT_CI107_RESERVATION_SHA256 = "5eab4ff8ef2cb4fa8d4952e9c25c0f413bd9d79394d158c36e68dddb140d2fe4"
SPENT_CI108_NONCE = "c25bab5386584a6ef6ffedd433aa3807"
SPENT_CI108_RESERVATION_SHA256 = "1b5f87f433795555c9d4d35422367f7793415812bf7a9f30c5ab7a2e17b5d7e0"
SPENT_CI109_NONCE = "07363c3222533f03509292d257ec80ea"
SPENT_CI109_RESERVATION_SHA256 = "54a68f2f310af6dc120cc5093a48141ef3847e2b583f33a1fe7cf69d3daa8ea4"
SPENT_CI113_NONCE, SPENT_CI113_RESERVATION_SHA256 = "e64f3c00f5e534736056558e3048ad5a", "c8944eaa5913f57cd94cb6f72ddb4eda0380925c54193e1f0e65163d4766b565"
SPENT_CI114_NONCE, SPENT_CI114_RESERVATION_SHA256 = "1e26115a9014b0d1426080a7caa57138", "2b66689167899aafb2f537ae4db3d50ddceb8e464128f71979693c9eb0dc2fe6"
SPENT_CI115_NONCE, SPENT_CI115_RESERVATION_SHA256 = "c7ce7c0b96549e046af7a5ec4e9b95e4", "e9d68de8dbf1a127bd9c1786606aa5e5015b2e6961ba18bca3c9c4422db50b4f"
SPENT_CI116_NONCE, SPENT_CI116_RESERVATION_SHA256 = "dd2c3169bc2b0e79796ae2ec5b0015c5", "3fb363949738bc8d84b218b1877c1db94b5b62c1c986d46df205358870bc5aa8"
SPENT_CI117_NONCE, SPENT_CI117_RESERVATION_SHA256 = "691c3087f8d8c28b38b5c0418ed7ae81", "636e08b89c0f3cea4c61a624599eb6587aaefcc24504f1747bb1b0928caf0b43"
SPENT_CI118_NONCE, SPENT_CI118_RESERVATION_SHA256 = "1bfaebc9765b76def50f55908f7f3579", "ecd61f00a7aa7f965271cff979401f08a72a273bb9db2ea949d0d3ddee230b39"
SPENT_CI119_NONCE, SPENT_CI119_RESERVATION_SHA256 = "605c7e268ab32c33645b9c605a6a6d22", "60ffd5feef73ab9b1b0b7ebbe2ec8ed0c1c67aa4419c3da098a7228e6bacaafe"
SPENT_CI120_NONCE, SPENT_CI120_RESERVATION_SHA256 = "48d97c99d6ea3225e46a07433c31e720", "256702bd2bc17074c14211a54537729b73770cc7856fcbfc941d0a35ff54be7c"
SPENT_CI121_NONCE, SPENT_CI121_RESERVATION_SHA256 = 'bfa7eea1d4b87aa74e226ae6846f8acf', 'af956df87d5302591c4d20bc7472209db6899dfbade3c81379822e9b477709f4'
SPENT_CI122_NONCE, SPENT_CI122_RESERVATION_SHA256 = '18bed730530223b7379a786bf28b3c58', '85e32ab4115cf9f4e2c2cf15f0521a2d4a1edecee15e2168134ae2b9e6ddb6c8'
SUPERSEDED_CI123_REVIEW1_NONCE, SUPERSEDED_CI123_REVIEW1_RESERVATION_SHA256 = '323ec566f05b8aa1f3d5bfc0cf5f71a5', 'ebf9959dccd7ea82656d5c8415be75ca134ea1bb2082b0f3e78606ead5bae883'
SUPERSEDED_CI110_NONCE = "387538b9616b4261f0d25044aef0889e"
SUPERSEDED_CI110_RESERVATION_SHA256 = "3ba9fcb000e4acd5090ecde3fd7150b214aa8a6d6b741fdba743ac45760d0855"
SUPERSEDED_CI106_REV1_NONCE = "ddd4357249dc922f90ca6acbbfd72050"
SUPERSEDED_CI106_REV1_RESERVATION_SHA256 = "d6cb3530a66cb2f8d3ed82a1063b38d7fed20892b85c59bf2a9295b370de837f"
SUPERSEDED_CONTEXT_REV3_NONCE = "14cc664cdb3b09ba1993beb070983795"
SUPERSEDED_CONTEXT_REV3_RESERVATION_SHA256 = "7b22fe6956d6799d350c53bbf29cc94946dba6fc5663f5d1cd9d92e1a2b6942b"
SUPERSEDED_CONTEXT_REV2_NONCE = "ab31ea6d1199edcca4bfabddfb81ddfd"
SUPERSEDED_CONTEXT_REV2_RESERVATION_SHA256 = "4cad8bef7f6a74ef5b152ab83fbad78cb08e5e502669cff24d8e56a447eac6c1"
SUPERSEDED_CONTEXT_REV1_NONCE = "93d9f509e46c6cb9eb9b05db7e0881ed"
SUPERSEDED_CONTEXT_REV1_RESERVATION_SHA256 = "96b204415efc4c9dee2cb9bbc3602e51411a23b1d72121bcf7051d581d3ab758"
SUPERSEDED_W2_NONCE = "cb637c3b41e4427491dcf7bc2c83e0ec"
SUPERSEDED_W2_RESERVATION_SHA256 = "922395c6167f8ebe47f192a32b2e7834c8f5c53a1c7bfbe04d1d1ad2f422e3a8"
SUPERSEDED_W2_REV2_NONCE = "d16a2474e8f841e489cf44e0d789da8b"
SUPERSEDED_W2_REV2_RESERVATION_SHA256 = "aa7ff667131b61c8070a3dfb45ae0efea197fe2fb89e5b509fd30bfed31aac5b"
SUPERSEDED_W3_REV1_NONCE = "81d48773f8793cf5219279819b968c4a"
SUPERSEDED_W3_REV1_RESERVATION_SHA256 = "f62ac5cde2fb8ce186d553e55723630010123bc8a4efa8897fa35c64a1a7bcdb"
DEFAULT_GRANT_RELPATH = Path("tools/ci/d12_system_build_grant.json")
DEFAULT_CANDIDATE_RELPATH = Path("tools/ci/d12_hosted_candidate.json")
MAX_SYSTEM_GRANT_BYTES = MAX_SYSTEM_PROOF_BYTES = 16384
GRANT_TOP_LEVEL_KEYS = frozenset({
    "schema", "nonce", "reservation_sha256", "repository", "workflow_path",
    "pull_request", "event_action", "head_ref", "base_ref", "before", "base",
    "workflow_ordinal", "workflow_attempt", "platform", "owner",
    "maximum_total", "maximum_per_platform", "approval_sha256",
    "ledger_before_sha256", "sdk_recipe_sha256", "d12_context"})
D12_CONTEXT_KEYS = frozenset({
    "source_sha256", "recipe_sha256", "dockerfile_sha256", "context_file_count"})
PROOF_TOP_LEVEL_KEYS = frozenset({
    "schema", "nonce", "reservation_sha256", "grant_sha256",
    "expected_candidate_sha256", "raw_event_sha256", "repository", "workflow_path", "owner",
    "platform", "pull_request", "approval_id", "event_action", "head_ref",
    "base_ref", "before", "after", "base", "candidate_sha", "candidate_tree",
    "candidate_base_parent", "candidate_head_parent", "workflow_ordinal",
    "workflow_attempt", "run_id", "native_host", "sdk_recipe_sha256",
    "d12_context", "release_manifest"})


def _validate_d12_context(ctx: object, *, sdk_recipe_sha256: str) -> dict[str, Any]:
    if not isinstance(ctx, Mapping) or set(ctx.keys()) != D12_CONTEXT_KEYS:
        raise D12SystemGrantError("d12_context keys do not match closed schema")
    src, rec, df = ctx.get("source_sha256"), ctx.get("recipe_sha256"), ctx.get("dockerfile_sha256")
    cnt = ctx.get("context_file_count")
    if not (_is_hex64(src) and _is_hex64(rec) and _is_hex64(df)):
        raise D12SystemGrantError("d12_context digests must be 64 lowercase hex")
    if len({src, rec, df, sdk_recipe_sha256}) != 4:
        raise D12SystemGrantError("d12_context and sdk_recipe_sha256 digests must be distinct")
    if not _is_strict_int(cnt) or int(cnt) <= 0:
        raise D12SystemGrantError("d12_context.context_file_count must be positive int")
    return dict(ctx)


def validate_system_build_grant(
    record: Mapping[str, Any], *,
    expected_candidate: Mapping[str, Any] | None = None,
    frozen_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record.keys()) != GRANT_TOP_LEVEL_KEYS:
        raise D12SystemGrantError("system build grant keys do not match closed schema")
    for key, expected in (
        ("schema", SYSTEM_BUILD_GRANT_SCHEMA), ("repository", EXPECTED_REPOSITORY),
        ("workflow_path", EXPECTED_WORKFLOW_PATH), ("event_action", "synchronize"),
        ("head_ref", "staging"), ("base_ref", "main"), ("platform", "linux/amd64"),
        ("owner", EXPECTED_SYSTEM_OWNER),
    ):
        if record.get(key) != expected:
            raise D12SystemGrantError(f"system build grant {key}={record.get(key)!r} != {expected!r}")
    for key, expected_int in (
        ("pull_request", 23), ("workflow_ordinal", 123), ("workflow_attempt", 1),
        ("maximum_total", 34), ("maximum_per_platform", 34),
    ):
        val = record.get(key)
        if not _is_strict_int(val) or val != expected_int:
            raise D12SystemGrantError(f"system build grant {key} must be strict int {expected_int}")
    if not _is_hex32(record.get("nonce")):
        raise D12SystemGrantError("system build grant nonce must be 32 lowercase hex")
    for sha_key in ("reservation_sha256", "approval_sha256", "ledger_before_sha256", "sdk_recipe_sha256"):
        if not _is_hex64(record.get(sha_key)):
            raise D12SystemGrantError(f"system build grant {sha_key} must be 64 lowercase hex")
    if record["nonce"] in (SPENT_CI69_NONCE, SPENT_CI70_NONCE, SPENT_CI71_NONCE, SPENT_CI72_NONCE, SPENT_CI85_NONCE, SPENT_CI86_NONCE, SPENT_CI87_NONCE, SPENT_CI91_NONCE, SPENT_CI92_NONCE, SPENT_CI93_NONCE, SPENT_CI94_NONCE, SPENT_CI95_NONCE, SPENT_CI96_NONCE, SPENT_CI97_NONCE, SPENT_CI98_NONCE, SPENT_CI99_NONCE, SPENT_CI100_NONCE, SPENT_CI101_NONCE, SPENT_CI102_NONCE, SPENT_CI103_NONCE, SPENT_CI104_NONCE, SPENT_CI105_NONCE, SPENT_CI106_NONCE, SPENT_CI107_NONCE, SPENT_CI108_NONCE, SPENT_CI109_NONCE, SPENT_CI113_NONCE, SPENT_CI114_NONCE, SPENT_CI115_NONCE, SPENT_CI116_NONCE, SPENT_CI117_NONCE, SPENT_CI118_NONCE, SPENT_CI119_NONCE, SPENT_CI120_NONCE, SPENT_CI121_NONCE, SPENT_CI122_NONCE, SUPERSEDED_CI123_REVIEW1_NONCE, SUPERSEDED_CI110_NONCE, SUPERSEDED_CI106_REV1_NONCE, SUPERSEDED_CONTEXT_REV3_NONCE, SUPERSEDED_CONTEXT_REV2_NONCE, SUPERSEDED_CONTEXT_REV1_NONCE, SUPERSEDED_W2_NONCE, SUPERSEDED_W2_REV2_NONCE, SUPERSEDED_W3_REV1_NONCE) or record["reservation_sha256"] in (
        SPENT_CI69_RESERVATION_SHA256, SPENT_CI70_RESERVATION_SHA256, SPENT_CI71_RESERVATION_SHA256, SPENT_CI72_RESERVATION_SHA256, SPENT_CI85_RESERVATION_SHA256, SPENT_CI86_RESERVATION_SHA256, SPENT_CI87_RESERVATION_SHA256, SPENT_CI91_RESERVATION_SHA256, SPENT_CI92_RESERVATION_SHA256, SPENT_CI93_RESERVATION_SHA256, SPENT_CI94_RESERVATION_SHA256, SPENT_CI95_RESERVATION_SHA256, SPENT_CI96_RESERVATION_SHA256, SPENT_CI97_RESERVATION_SHA256, SPENT_CI98_RESERVATION_SHA256, SPENT_CI99_RESERVATION_SHA256, SPENT_CI100_RESERVATION_SHA256, SPENT_CI101_RESERVATION_SHA256, SPENT_CI102_RESERVATION_SHA256, SPENT_CI103_RESERVATION_SHA256, SPENT_CI104_RESERVATION_SHA256, SPENT_CI105_RESERVATION_SHA256, SPENT_CI106_RESERVATION_SHA256, SPENT_CI107_RESERVATION_SHA256, SPENT_CI108_RESERVATION_SHA256, SPENT_CI109_RESERVATION_SHA256, SPENT_CI113_RESERVATION_SHA256, SPENT_CI114_RESERVATION_SHA256, SPENT_CI115_RESERVATION_SHA256, SPENT_CI116_RESERVATION_SHA256, SPENT_CI117_RESERVATION_SHA256, SPENT_CI118_RESERVATION_SHA256, SPENT_CI119_RESERVATION_SHA256, SPENT_CI120_RESERVATION_SHA256, SPENT_CI121_RESERVATION_SHA256, SPENT_CI122_RESERVATION_SHA256, SUPERSEDED_CI123_REVIEW1_RESERVATION_SHA256, SUPERSEDED_CI110_RESERVATION_SHA256, SUPERSEDED_CI106_REV1_RESERVATION_SHA256, SUPERSEDED_CONTEXT_REV3_RESERVATION_SHA256, SUPERSEDED_CONTEXT_REV2_RESERVATION_SHA256, SUPERSEDED_CONTEXT_REV1_RESERVATION_SHA256, SUPERSEDED_W2_RESERVATION_SHA256, SUPERSEDED_W2_REV2_RESERVATION_SHA256, SUPERSEDED_W3_REV1_RESERVATION_SHA256):
        raise D12SystemGrantError("system build grant reuses spent CI69/CI70/CI71/CI72/CI85/CI86/CI87/CI91/CI92/CI93/CI94/CI95/CI96/CI97/CI98/CI99/CI100/CI101/CI102/CI103/CI104 or spent CI105/CI106/CI107/CI108/CI109/CI113 or superseded context nonce or reservation")
    before, base = record.get("before"), record.get("base")
    if not (_is_hex40(before) and _is_hex40(base)) or before == base:
        raise D12SystemGrantError("system build grant synchronize before/base must be distinct 40-hex")
    for pin_k, pin_v in (
        ("before", EXPECTED_BEFORE_SHA), ("base", EXPECTED_BASE_SHA),
        ("approval_sha256", EXPECTED_APPROVAL_SHA256), ("ledger_before_sha256", EXPECTED_LEDGER_BEFORE_SHA256),
    ):
        if record.get(pin_k) != pin_v:
            raise D12SystemGrantError(f"system build grant {pin_k} does not match pinned REPOMAP-CLOE-RESOURCE-EXPERIENCE1 CI123 REVIEW2 replacement authority")
    sdk_sha = str(record["sdk_recipe_sha256"])
    d12_ctx = _validate_d12_context(record.get("d12_context"), sdk_recipe_sha256=sdk_sha)
    if expected_candidate is not None:
        exp_ctx, exp_sdk = expected_candidate.get("d12_context"), expected_candidate.get("sdk_sandbox")
        if not isinstance(exp_ctx, Mapping) or dict(d12_ctx) != dict(exp_ctx):
            raise D12SystemGrantError("system build grant d12_context disagrees with d12_hosted_candidate.json")
        if not isinstance(exp_sdk, Mapping) or sdk_sha != exp_sdk.get("sdk_recipe_sha256"):
            raise D12SystemGrantError("system build grant sdk_recipe_sha256 disagrees with d12_hosted_candidate.json")
    if frozen_identity is not None:
        for k in D12_CONTEXT_KEYS:
            if d12_ctx.get(k) != frozen_identity.get(k):
                raise D12SystemGrantError(f"system build grant d12_context.{k} disagrees with live repository")
    return dict(record)


def load_and_validate_system_build_grant(
    grant_path: Path, *,
    expected_candidate: Mapping[str, Any] | None = None,
    frozen_identity: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    parsed, _raw, sha = read_regular_json_object(
        grant_path, label="system build grant", max_bytes=MAX_SYSTEM_GRANT_BYTES
    )
    return validate_system_build_grant(
        parsed, expected_candidate=expected_candidate, frozen_identity=frozen_identity
    ), sha


def build_system_admission_proof(
    *, grant: Mapping[str, Any], grant_sha256: str, expected_candidate_sha256: str,
    raw_event_sha256: str, after: str, candidate_sha: str, candidate_tree: str,
    candidate_base_parent: str, candidate_head_parent: str, run_id: str,
    native_host: Mapping[str, str], libpq_version: int = D12_CANDIDATE_LIBPQ_VERSION,
    amd64_packages: Any = None,
) -> dict[str, Any]:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"] if amd64_packages is None else amd64_packages
    pr_num = int(grant["pull_request"])
    proof: dict[str, Any] = {
        "schema": SYSTEM_ADMISSION_PROOF_SCHEMA, "nonce": str(grant["nonce"]),
        "reservation_sha256": str(grant["reservation_sha256"]), "grant_sha256": grant_sha256,
        "expected_candidate_sha256": expected_candidate_sha256, "raw_event_sha256": raw_event_sha256,
        "repository": str(grant["repository"]),
        "workflow_path": str(grant["workflow_path"]), "owner": str(grant["owner"]),
        "platform": str(grant["platform"]), "pull_request": pr_num, "approval_id": f"pr-{pr_num}",
        "event_action": str(grant["event_action"]), "head_ref": str(grant["head_ref"]),
        "base_ref": str(grant["base_ref"]), "before": str(grant["before"]), "after": after,
        "base": str(grant["base"]), "candidate_sha": candidate_sha, "candidate_tree": candidate_tree,
        "candidate_base_parent": candidate_base_parent, "candidate_head_parent": candidate_head_parent,
        "workflow_ordinal": int(grant["workflow_ordinal"]), "workflow_attempt": int(grant["workflow_attempt"]),
        "run_id": run_id, "native_host": dict(native_host),
        "sdk_recipe_sha256": str(grant["sdk_recipe_sha256"]), "d12_context": dict(grant["d12_context"]),
        "release_manifest": {
            "libpq_version": libpq_version, "libpq5_version": str(pkg.libpq5_version),
            "libpq_sha256": str(pkg.libpq_sha256), "postgres_config_digest": str(pkg.postgres_config_digest),
        },
    }
    return validate_system_admission_proof(
        proof, grant=grant, grant_sha256=grant_sha256, expected_candidate_sha256=expected_candidate_sha256
    )


def validate_system_admission_proof(
    record: Mapping[str, Any], *, grant: Mapping[str, Any] | None = None,
    grant_sha256: str | None = None, expected_candidate_sha256: str | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record.keys()) != PROOF_TOP_LEVEL_KEYS:
        raise D12SystemGrantError("system admission proof keys do not match closed schema")
    for k, exp in (
        ("schema", SYSTEM_ADMISSION_PROOF_SCHEMA), ("repository", EXPECTED_REPOSITORY),
        ("workflow_path", EXPECTED_WORKFLOW_PATH), ("owner", EXPECTED_SYSTEM_OWNER),
        ("platform", "linux/amd64"), ("event_action", "synchronize"),
        ("head_ref", "staging"), ("base_ref", "main"), ("approval_id", "pr-23"),
    ):
        if record.get(k) != exp:
            raise D12SystemGrantError(f"system admission proof {k}={record.get(k)!r} != {exp!r}")
    for k, exp_int in (("pull_request", 23), ("workflow_ordinal", 123), ("workflow_attempt", 1)):
        val = record.get(k)
        if not _is_strict_int(val) or val != exp_int:
            raise D12SystemGrantError(f"system admission proof {k} must be strict int {exp_int}")
    if not _is_hex32(record.get("nonce")):
        raise D12SystemGrantError("system admission proof nonce must be 32 lowercase hex")
    for sha_k in (
        "reservation_sha256", "grant_sha256", "expected_candidate_sha256",
        "raw_event_sha256", "sdk_recipe_sha256",
    ):
        if not _is_hex64(record.get(sha_k)):
            raise D12SystemGrantError(f"system admission proof {sha_k} must be 64-hex")
    if record["nonce"] in (SPENT_CI69_NONCE, SPENT_CI70_NONCE, SPENT_CI71_NONCE, SPENT_CI72_NONCE, SPENT_CI85_NONCE, SPENT_CI86_NONCE, SPENT_CI87_NONCE, SPENT_CI91_NONCE, SPENT_CI92_NONCE, SPENT_CI93_NONCE, SPENT_CI94_NONCE, SPENT_CI95_NONCE, SPENT_CI96_NONCE, SPENT_CI97_NONCE, SPENT_CI98_NONCE, SPENT_CI99_NONCE, SPENT_CI100_NONCE, SPENT_CI101_NONCE, SPENT_CI102_NONCE, SPENT_CI103_NONCE, SPENT_CI104_NONCE, SPENT_CI105_NONCE, SPENT_CI106_NONCE, SPENT_CI107_NONCE, SPENT_CI108_NONCE, SPENT_CI109_NONCE, SPENT_CI113_NONCE, SPENT_CI114_NONCE, SPENT_CI115_NONCE, SPENT_CI116_NONCE, SPENT_CI117_NONCE, SPENT_CI118_NONCE, SPENT_CI119_NONCE, SPENT_CI120_NONCE, SPENT_CI121_NONCE, SPENT_CI122_NONCE, SUPERSEDED_CI123_REVIEW1_NONCE, SUPERSEDED_CI110_NONCE, SUPERSEDED_CI106_REV1_NONCE, SUPERSEDED_CONTEXT_REV3_NONCE, SUPERSEDED_CONTEXT_REV2_NONCE, SUPERSEDED_CONTEXT_REV1_NONCE, SUPERSEDED_W2_NONCE, SUPERSEDED_W2_REV2_NONCE, SUPERSEDED_W3_REV1_NONCE) or record["reservation_sha256"] in (
        SPENT_CI69_RESERVATION_SHA256, SPENT_CI70_RESERVATION_SHA256, SPENT_CI71_RESERVATION_SHA256, SPENT_CI72_RESERVATION_SHA256, SPENT_CI85_RESERVATION_SHA256, SPENT_CI86_RESERVATION_SHA256, SPENT_CI87_RESERVATION_SHA256, SPENT_CI91_RESERVATION_SHA256, SPENT_CI92_RESERVATION_SHA256, SPENT_CI93_RESERVATION_SHA256, SPENT_CI94_RESERVATION_SHA256, SPENT_CI95_RESERVATION_SHA256, SPENT_CI96_RESERVATION_SHA256, SPENT_CI97_RESERVATION_SHA256, SPENT_CI98_RESERVATION_SHA256, SPENT_CI99_RESERVATION_SHA256, SPENT_CI100_RESERVATION_SHA256, SPENT_CI101_RESERVATION_SHA256, SPENT_CI102_RESERVATION_SHA256, SPENT_CI103_RESERVATION_SHA256, SPENT_CI104_RESERVATION_SHA256, SPENT_CI105_RESERVATION_SHA256, SPENT_CI106_RESERVATION_SHA256, SPENT_CI107_RESERVATION_SHA256, SPENT_CI108_RESERVATION_SHA256, SPENT_CI109_RESERVATION_SHA256, SPENT_CI113_RESERVATION_SHA256, SPENT_CI114_RESERVATION_SHA256, SPENT_CI115_RESERVATION_SHA256, SPENT_CI116_RESERVATION_SHA256, SPENT_CI117_RESERVATION_SHA256, SPENT_CI118_RESERVATION_SHA256, SPENT_CI119_RESERVATION_SHA256, SPENT_CI120_RESERVATION_SHA256, SPENT_CI121_RESERVATION_SHA256, SPENT_CI122_RESERVATION_SHA256, SUPERSEDED_CI123_REVIEW1_RESERVATION_SHA256, SUPERSEDED_CI110_RESERVATION_SHA256, SUPERSEDED_CI106_REV1_RESERVATION_SHA256, SUPERSEDED_CONTEXT_REV3_RESERVATION_SHA256, SUPERSEDED_CONTEXT_REV2_RESERVATION_SHA256, SUPERSEDED_CONTEXT_REV1_RESERVATION_SHA256, SUPERSEDED_W2_RESERVATION_SHA256, SUPERSEDED_W2_REV2_RESERVATION_SHA256, SUPERSEDED_W3_REV1_RESERVATION_SHA256):
        raise D12SystemGrantError("system admission proof reuses spent CI69/CI70/CI71/CI72/CI85/CI86/CI87/CI91/CI92/CI93/CI94/CI95/CI96/CI97/CI98/CI99/CI100/CI101/CI102/CI103/CI104 or spent CI105/CI106/CI107/CI108/CI109/CI113 or superseded context nonce or reservation")
    for git_k in (
        "before", "after", "base", "candidate_sha", "candidate_tree",
        "candidate_base_parent", "candidate_head_parent",
    ):
        if not _is_hex40(record.get(git_k)):
            raise D12SystemGrantError(f"system admission proof {git_k} must be 40-hex")
    if record["before"] != EXPECTED_BEFORE_SHA or record["base"] != EXPECTED_BASE_SHA:
        raise D12SystemGrantError("system admission proof before/base does not match pinned REPOMAP-CLOE-RESOURCE-EXPERIENCE1 CI123 REVIEW2 replacement authority")
    if (
        record["after"] == record["before"]
        or record["candidate_base_parent"] != record["base"]
        or record["candidate_head_parent"] != record["after"]
        or record["candidate_sha"] in {record["base"], record["after"]}
    ):
        raise D12SystemGrantError("system admission proof Git parent/synchronize topology invalid")
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not run_id.isdigit():
        raise D12SystemGrantError("system admission proof run_id must be digits-only string")
    host = record.get("native_host")
    if not isinstance(host, Mapping) or dict(host) != {
        "runner_os": "Linux", "runner_arch": "X64", "host_kernel": "Linux", "host_arch": "x86_64",
    }:
        raise D12SystemGrantError("system admission proof native_host must be Linux/X64/x86_64")
    d12_ctx = _validate_d12_context(
        record.get("d12_context"), sdk_recipe_sha256=str(record["sdk_recipe_sha256"])
    )
    rel_man = record.get("release_manifest")
    if not isinstance(rel_man, Mapping) or set(rel_man.keys()) != {
        "libpq_version", "libpq5_version", "libpq_sha256", "postgres_config_digest",
    }:
        raise D12SystemGrantError("system admission proof release_manifest keys invalid")
    if (
        not _is_strict_int(rel_man.get("libpq_version"))
        or int(rel_man["libpq_version"]) < PRODUCT_MINIMUM_LIBPQ_VERSION
        or not _is_hex64(rel_man.get("libpq_sha256"))
        or not str(rel_man.get("postgres_config_digest", "")).startswith("sha256:")
    ):
        raise D12SystemGrantError("system admission proof release_manifest values invalid")
    if grant_sha256 is not None and record["grant_sha256"] != grant_sha256:
        raise D12SystemGrantError("system admission proof grant_sha256 mismatch")
    if (
        expected_candidate_sha256 is not None
        and record["expected_candidate_sha256"] != expected_candidate_sha256
    ):
        raise D12SystemGrantError("system admission proof expected_candidate_sha256 mismatch")
    if grant is not None:
        for shared_k in (
            "nonce", "reservation_sha256", "repository", "workflow_path",
            "pull_request", "event_action", "head_ref", "base_ref", "before",
            "base", "workflow_ordinal", "workflow_attempt", "platform", "owner",
            "sdk_recipe_sha256",
        ):
            if record.get(shared_k) != grant.get(shared_k):
                raise D12SystemGrantError(f"system admission proof {shared_k} disagrees with grant")
        if d12_ctx != dict(grant.get("d12_context") or {}):
            raise D12SystemGrantError("system admission proof d12_context disagrees with grant")
    return dict(record)


def write_system_admission_proof(proof_path: Path, payload: Mapping[str, Any]) -> str:
    validated = validate_system_admission_proof(payload)
    parent = proof_path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(parent, 0o700)
    raw = (json.dumps(validated, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(raw) > MAX_SYSTEM_PROOF_BYTES:
        raise D12SystemGrantError(f"system admission proof exceeds {MAX_SYSTEM_PROOF_BYTES} bytes")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(proof_path, flags, 0o600)
    except FileExistsError as exc:
        raise D12SystemGrantError(f"system admission proof already exists: {proof_path}") from exc
    except OSError as exc:
        raise D12SystemGrantError(f"cannot create system admission proof {proof_path}: {exc}") from exc
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    dir_fd = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return hashlib.sha256(raw).hexdigest()


def load_and_validate_system_admission_proof(
    proof_path: Path, *, grant: Mapping[str, Any] | None = None,
    grant_sha256: str | None = None, expected_candidate_sha256: str | None = None,
    require_mode_0600: bool = True, require_parent_mode_0700: bool = False,
) -> tuple[dict[str, Any], bytes, str]:
    parsed, raw, sha = read_regular_json_object(
        proof_path, label="system admission proof", max_bytes=MAX_SYSTEM_PROOF_BYTES,
        require_mode_0600=require_mode_0600, require_parent_mode_0700=require_parent_mode_0700,
    )
    return validate_system_admission_proof(
        parsed, grant=grant, grant_sha256=grant_sha256, expected_candidate_sha256=expected_candidate_sha256
    ), raw, sha


def verify_host_system_proof_for_dispatch(
    args: Any, *, raw_argv: list[str] | None = None, repo_root: Path,
    env: Mapping[str, str] | None = None, uname_fn: Callable[[], tuple[str, str]] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    frozen_identity_fn: Callable[..., dict[str, Any]] | None = None,
    grant_path: Path | None = None, expected_candidate_path: Path | None = None,
) -> dict[str, Any]:
    from ci.d12_system_proof_host import verify_host_proof_against_live_environment

    return verify_host_proof_against_live_environment(
        args, raw_argv=raw_argv, repo_root=repo_root, env=env, uname_fn=uname_fn,
        runner=runner, frozen_identity_fn=frozen_identity_fn, grant_path=grant_path,
        expected_candidate_path=expected_candidate_path,
    )
