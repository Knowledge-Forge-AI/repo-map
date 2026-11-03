"""Source-pinned admission publisher executed inside the SDK container."""

REMOTE_ADMISSION_SOURCE = r'''import hashlib, io, json, os, re, stat, sys, tarfile

MAX_ADMISSION_BYTES = 512 * 1024
MAX_MARKER_BYTES = 4096
MAX_TAR_BYTES = MAX_ADMISSION_BYTES + MAX_MARKER_BYTES + 4096
PREFIX = "w5-component-"
SCHEMA = "cloe-w5-controller-admission-ready-v1"
NAMES = {"controller.admission.json", "controller.admission.ready.json"}
NONCE = re.compile(r"[0-9a-f]{64}\Z")
ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def fail():
    raise SystemExit(2)


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            fail()
        result[key] = value
    return result


def request_parts(value):
    if type(value) is not str or not value or len(value) > 4096:
        fail()
    parts = value.split("/")
    if len(parts) < 2 or len(parts) > 16:
        fail()
    if any(not part or part in {".", ".."} or "\\" in part or "\x00" in part for part in parts):
        fail()
    if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", part) is None for part in parts):
        fail()
    if parts[-1] != "request.json" or not parts[-2].startswith(PREFIX):
        fail()
    nonce = parts[-2][len(PREFIX):]
    if NONCE.fullmatch(nonce) is None:
        fail()
    return parts, nonce


def open_directory(parts):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in ("sandbox-scratch", "test-scratch", *parts):
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def validate_headers(raw):
    offset = 0
    members = 0
    while offset + 512 <= len(raw):
        block = raw[offset:offset + 512]
        if block == b"\0" * 512:
            if len(raw) - offset < 1024 or raw[offset:offset + 1024] != b"\0" * 1024:
                fail()
            if any(raw[offset + 1024:]) or members != 2:
                fail()
            return
        if block[156:157] not in {b"0", b"\0"}:
            fail()
        field = block[124:136].rstrip(b"\0 ")
        try:
            size = int(field or b"0", 8)
        except ValueError:
            fail()
        if size < 0 or size > MAX_TAR_BYTES:
            fail()
        members += 1
        if members > 2:
            fail()
        end = offset + 512 + ((size + 511) // 512) * 512
        if end > len(raw):
            fail()
        offset = end
    fail()


def read_tar(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_TAR_BYTES:
        fail()
    validate_headers(raw)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            found = {}
            for info in archive:
                if len(found) >= 2 or info.pax_headers:
                    fail()
                if info.name not in NAMES or info.name in found:
                    fail()
                if info.type not in {tarfile.REGTYPE, tarfile.AREGTYPE}:
                    fail()
                limit = MAX_MARKER_BYTES if info.name.endswith("ready.json") else MAX_ADMISSION_BYTES
                if info.size < 1 or info.size > limit:
                    fail()
                source = archive.extractfile(info)
                if source is None:
                    fail()
                content = source.read(info.size + 1)
                if len(content) != info.size:
                    fail()
                found[info.name] = content
            if set(found) != NAMES:
                fail()
            return found
    except (OSError, EOFError, tarfile.TarError, ValueError):
        fail()


def validate_marker(raw, admission, nonce):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_MARKER_BYTES:
        fail()
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1 or b"\r" in raw:
        fail()
    try:
        document = json.loads(raw[:-1].decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: fail())
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        fail()
    if not isinstance(document, dict) or set(document) != {
        "schema", "attempt_id", "nonce", "request_sha256", "admission_sha256", "admission_bytes"
    }:
        fail()
    if (
        document["schema"] != SCHEMA
        or type(document["attempt_id"]) is not str
        or ATTEMPT.fullmatch(document["attempt_id"]) is None
        or document["nonce"] != nonce
        or NONCE.fullmatch(document["nonce"]) is None
        or type(document["request_sha256"]) is not str
        or DIGEST.fullmatch(document["request_sha256"]) is None
        or type(document["admission_sha256"]) is not str
        or DIGEST.fullmatch(document["admission_sha256"]) is None
        or type(document["admission_bytes"]) is not int
        or document["admission_bytes"] != len(admission)
        or document["admission_sha256"] != "sha256:" + hashlib.sha256(admission).hexdigest()
    ):
        fail()
    try:
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError):
        fail()
    if raw != canonical:
        fail()


def write_file(fd, name, content, created_names):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    handle = os.open(name, flags, 0o600, dir_fd=fd)
    created_names.append(name)
    try:
        offset = 0
        while offset < len(content):
            offset += os.write(handle, content[offset:])
        os.fsync(handle)
    finally:
        os.close(handle)


if len(sys.argv) != 2:
    fail()
parts, nonce = request_parts(sys.argv[1])
payload = sys.stdin.buffer.read(MAX_TAR_BYTES + 1)
files = read_tar(payload)
admission = files["controller.admission.json"]
marker = files["controller.admission.ready.json"]
validate_marker(marker, admission, nonce)
directory = open_directory(parts[:-1])
created_names = []
try:
    for name in NAMES:
        try:
            os.stat(name, dir_fd=directory, follow_symlinks=False)
            fail()
        except FileNotFoundError:
            pass
    write_file(directory, "controller.admission.json", admission, created_names)
    write_file(directory, "controller.admission.ready.json", marker, created_names)
    os.fsync(directory)
except BaseException:
    for name in reversed(created_names):
        try:
            os.unlink(name, dir_fd=directory)
        except OSError:
            pass
    raise
finally:
    os.close(directory)
'''

__all__ = ["REMOTE_ADMISSION_SOURCE"]
