"""Trusted setup-only writer for the sealed runtime prefix (spec 5.3).

Runs once as container UID 0 without capabilities, before any target byte
exists. Stdin carries a magic line, one JSON header line and the payloads.
The writer verifies every payload and wheel archive in memory, writes the
closed member set through no-follow descriptor traversal with exclusive
creation, seals the tree root-owned and read-only, prints one summary line
and exits. The parent does not trust that summary; it reads every byte back.
Standalone standard library only.
"""

import base64
import csv
import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile

RUNTIME_ROOT = "/opt/repomap-rust"
MAGIC = b"REPOMAP-RUST-SETUP-1\n"
MAX_HEADER = 65_536
MAX_PAYLOAD = 4 * 1_048_576
MAX_ARCHIVE = 8 * 1_048_576
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
WHEEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,200}\.whl")
NOTICE_NAMES = frozenset({"tree-sitter-core-LICENSE", "tree-sitter-unicode-LICENSE"})
SHA256 = re.compile(r"[0-9a-f]{64}")
HELPER_NAME = "parse_helper.py"
ZIP_DIRECTORY_MODE = 0o755


class Refused(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def exact_int(value, low, high):
    return type(value) is int and low <= value <= high


def reject_number(_value):
    raise ValueError("number_refused")


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_key")
        result[key] = value
    return result


def safe_name(name):
    require(type(name) is str and name and "\\" not in name and "\x00" not in name, "unsafe_member_name")
    require(not name.startswith("/") and not name.endswith("/"), "unsafe_member_name")
    require(all(part not in ("", ".", "..") for part in name.split("/")), "unsafe_member_name")
    return name


def safe_directory_name(name):
    require(type(name) is str and name.endswith("/"), "unsafe_member_name")
    safe_name(name[:-1])
    return name


def required_directory_names(names):
    directories: set[str] = set()
    for name in names:
        parts = name.split("/")[:-1]
        directories.update("/".join(parts[:index]) + "/"
                           for index in range(1, len(parts) + 1))
    return directories


def read_exact(stream, count):
    chunks = []
    remaining = count
    while remaining:
        chunk = stream.read(min(remaining, 65_536))
        require(chunk, "short_payload")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def parse_header(stream):
    require(stream.readline(len(MAGIC) + 1) == MAGIC, "bad_magic")
    line = stream.readline(MAX_HEADER + 1)
    require(line.endswith(b"\n") and len(line) <= MAX_HEADER, "bad_header")
    try:
        header = json.loads(line.decode("ascii"), object_pairs_hook=unique_pairs,
                            parse_float=reject_number, parse_constant=reject_number)
    except (UnicodeDecodeError, ValueError):
        raise Refused("bad_header") from None
    require(type(header) is dict and set(header) == {"v", "payloads"}
            and exact_int(header["v"], 1, 1), "bad_header")
    payloads = header["payloads"]
    require(type(payloads) is list and 3 <= len(payloads) <= 8, "bad_header")
    classes = [item.get("class") if type(item) is dict else None for item in payloads]
    wheels = classes.count("wheel")
    require(wheels >= 1 and classes == ["wheel"] * wheels + ["helper"] + ["notice"] * (len(classes) - wheels - 1),
            "bad_payload_order")
    for item in payloads:
        check_payload_entry(item)
    require(sum(item["size"] for item in payloads) <= MAX_PAYLOAD, "payload_too_large")
    return payloads


def check_payload_entry(item):
    keys = {"class", "name", "size", "sha256"}
    if item["class"] == "wheel":
        keys |= {"dist_info", "top_level", "members"}
    require(set(item) == keys, "bad_header")
    require(exact_int(item["size"], 0, MAX_PAYLOAD), "bad_header")
    require(type(item["sha256"]) is str and SHA256.fullmatch(item["sha256"]) is not None, "bad_header")
    name = item["name"]
    if item["class"] == "wheel":
        require(type(name) is str and WHEEL_NAME.fullmatch(name) is not None, "bad_header")
        require(type(item["dist_info"]) is str and item["dist_info"].endswith(".dist-info"), "bad_header")
        require(type(item["top_level"]) is list and all(type(v) is str for v in item["top_level"]), "bad_header")
        members = item["members"]
        require(type(members) is list and 1 <= len(members) <= 64, "bad_header")
        for member in members:
            require(type(member) is list and len(member) == 4, "bad_header")
            safe_name(member[0])
            require(exact_int(member[1], 0, MAX_ARCHIVE), "bad_header")
            require(type(member[2]) is str and SHA256.fullmatch(member[2]) is not None, "bad_header")
            require(exact_int(member[3], 0, 0o7777), "bad_header")
    elif item["class"] == "helper":
        require(name == HELPER_NAME, "bad_header")
    else:
        require(type(name) is str and name in NOTICE_NAMES, "bad_header")


def record_hash(data):
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def verify_wheel(data, item):
    expected = {member[0]: (member[1], member[2], member[3]) for member in item["members"]}
    require(len(expected) == len(item["members"]), "duplicate_member")
    expected_directories = required_directory_names(expected)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise Refused("invalid_archive") from None
    contents = {}
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        require(len(names) == len(set(names)), "duplicate_member")
        regular_infos = []
        for info in infos:
            if info.filename.endswith("/"):
                safe_directory_name(info.filename)
                require(info.filename[:-1] not in expected, "member_path_collision")
                require(info.filename in expected_directories, "unexpected_directory")
                require(info.flag_bits & 0x1 == 0, "encrypted_member")
                require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                        "compression_refused")
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                require(kind != stat.S_IFLNK, "symlink_member")
                require(kind == stat.S_IFDIR and stat.S_IMODE(mode) == ZIP_DIRECTORY_MODE,
                        "directory_mode_mismatch")
                require(info.file_size == 0, "directory_payload")
                continue
            safe_name(info.filename)
            base = info.filename.rsplit("/", 1)[-1]
            require(not base.endswith(".pth"), "pth_member")
            require(base != "entry_points.txt", "entry_points_member")
            head = info.filename.split("/", 1)[0]
            require(not head.endswith(".data"), "data_directory_member")
            require(not head.endswith(".dist-info") or head == item["dist_info"], "conflicting_distribution")
            require(head in item["top_level"], "unexpected_top_level")
            require(info.flag_bits & 0x1 == 0, "encrypted_member")
            require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "compression_refused")
            mode = info.external_attr >> 16
            require(not mode or stat.S_IFMT(mode) == stat.S_IFREG, "special_member")
            regular_infos.append(info)
        require({info.filename for info in regular_infos} == set(expected), "member_set_mismatch")
        require(sum(info.file_size for info in infos) <= MAX_ARCHIVE, "archive_too_large")
        for info in regular_infos:
            size, digest, mode = expected[info.filename]
            require(stat.S_IMODE(info.external_attr >> 16) == mode, "member_mode_mismatch")
            require(info.file_size == size, "member_size_mismatch")
            try:
                with archive.open(info) as handle:
                    content = handle.read(size + 1)
            except (zipfile.BadZipFile, ValueError, OSError, EOFError, RuntimeError):
                raise Refused("invalid_archive") from None
            require(len(content) == size and hashlib.sha256(content).hexdigest() == digest,
                    "member_digest_mismatch")
            contents[info.filename] = content
    verify_record(contents, item["dist_info"] + "/RECORD")
    return [(info.filename, contents[info.filename]) for info in regular_infos]


def verify_record(contents, record_name):
    require(record_name in contents, "record_missing")
    try:
        rows = list(csv.reader(io.StringIO(contents[record_name].decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error):
        raise Refused("record_invalid") from None
    seen = set()
    for row in rows:
        require(len(row) == 3 and row[0] not in seen, "record_invalid")
        seen.add(row[0])
        if row[0] == record_name:
            require(row[1] == "" and row[2] == "", "record_self_entry")
            continue
        require(row[0] in contents, "record_extra_entry")
        content = contents[row[0]]
        require(row[1] == record_hash(content) and row[2] == str(len(content)), "record_mismatch")
    require(seen == set(contents), "record_incomplete")


def plan_tree(payloads, blobs):
    files: dict[str, list[bytes]] = {}
    for item, blob in zip(payloads, blobs):
        if item["class"] == "wheel":
            for name, content in verify_wheel(blob, item):
                files.setdefault("site/" + name, []).append(content)
        elif item["class"] == "helper":
            files.setdefault("helper/" + HELPER_NAME, []).append(blob)
        else:
            files.setdefault("notices/" + item["name"], []).append(blob)
    require(all(len(value) == 1 for value in files.values()), "install_path_collision")
    result: dict[str, bytes] = {path: value[0] for path, value in files.items()}
    return result


def open_child_dir(parent_fd, name):
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    fd = os.open(name, DIR_FLAGS, dir_fd=parent_fd)
    require(stat.S_ISDIR(os.fstat(fd).st_mode), "not_directory")
    return fd


def write_tree(root_fd, files):
    require(os.listdir(root_fd) == [], "root_not_empty")
    directories = {"": root_fd}
    written = 0
    try:
        for path in sorted(files):
            parts = path.split("/")
            current = ""
            for part in parts[:-1]:
                child = part if not current else current + "/" + part
                if child not in directories:
                    directories[child] = open_child_dir(directories[current], part)
                current = child
            content = files[path]
            fd = os.open(parts[-1], FILE_FLAGS, 0o600, dir_fd=directories[current])
            try:
                view = memoryview(content)
                while view:
                    count = os.write(fd, view)
                    require(count > 0, "short_write")
                    view = view[count:]
                require(os.fstat(fd).st_size == len(content), "short_write")
                os.fchmod(fd, 0o555 if path.endswith(".so") else 0o444)
            finally:
                os.close(fd)
            written += 1
        for name in sorted(directories, key=lambda value: value.count("/") + (1 if value else 0),
                           reverse=True):
            os.fchmod(directories[name], 0o555)
    finally:
        for name, fd in directories.items():
            if name:
                os.close(fd)
    return written


def main():
    stream = sys.stdin.buffer
    try:
        payloads = parse_header(stream)
        blobs = [read_exact(stream, item["size"]) for item in payloads]
        require(stream.read(1) == b"", "trailing_bytes")
        for item, blob in zip(payloads, blobs):
            require(hashlib.sha256(blob).hexdigest() == item["sha256"], "payload_digest_mismatch")
        files = plan_tree(payloads, blobs)
        root_fd = os.open(RUNTIME_ROOT, DIR_FLAGS)
        try:
            written = write_tree(root_fd, files)
        finally:
            os.close(root_fd)
    except Refused as refusal:
        sys.stderr.write("setup_refused " + str(refusal) + "\n")
        return 2
    except Exception:  # bounded categorical diagnostic; no payload bytes are echoed
        sys.stderr.write("setup_refused internal_error\n")
        return 5
    sys.stdout.write("REPOMAP-RUST-SETUP-OK " + str(written) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
