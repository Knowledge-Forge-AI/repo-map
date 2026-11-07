"""Install readback, run as the parser principal before any target byte (spec 5.4).

Walks the runtime prefix in sorted order with no-follow ``lstat`` and emits,
per entry, one JSON header line followed by the raw bytes of each regular
file. Then it emits guest-observed mount, credential, scratch and interface
facts. A symlink, a special file or more than 8 MiB of output refuses. The
parent compares every byte with its own extraction; nothing here is trusted.
Standalone standard library only.
"""

import json
import errno
import fcntl
import os
import socket
import stat
import struct
import sys

RUNTIME_ROOT = "/opt/repomap-rust"
SCRATCH = "/scratch"
MAX_OUTPUT = 8 * 1_048_576
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
STATUS_PREFIXES = ("Uid:", "Gid:", "CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:",
                   "NoNewPrivs:", "Seccomp:")


class Refused(Exception):
    pass


class Sink:
    def __init__(self, stream):
        self.stream = stream
        self.total = 0

    def emit(self, data):
        self.total += len(data)
        if self.total > MAX_OUTPUT:
            raise Refused("readback_too_large")
        self.stream.write(data)

    def record(self, value):
        self.emit(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n")


def entry_header(path, info, kind):
    return {"t": "entry", "path": path, "type": kind, "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid, "gid": info.st_gid, "nlink": info.st_nlink,
            "size": info.st_size if kind == "f" else 0}


def read_file(dir_fd, name, expected):
    fd = os.open(name, READ_FLAGS, dir_fd=dir_fd)
    try:
        before = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size) != (expected.st_dev, expected.st_ino, expected.st_size):
            raise Refused("entry_changed")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 65_536))
            if not chunk:
                raise Refused("short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise Refused("entry_changed")
    finally:
        os.close(fd)
    return b"".join(chunks)


def walk(sink, dir_fd, prefix):
    count = 0
    for name in sorted(os.listdir(dir_fd)):
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        path = name if not prefix else prefix + "/" + name
        if stat.S_ISDIR(info.st_mode):
            sink.record(entry_header(path, info, "d"))
            child = os.open(name, DIR_FLAGS, dir_fd=dir_fd)
            try:
                count += 1 + walk(sink, child, path)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            sink.record(entry_header(path, info, "f"))
            sink.emit(read_file(dir_fd, name, info))
            count += 1
        else:
            raise Refused("special_or_symlink_entry")
    return count


def read_lines(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read(262_144)
    except OSError:
        return []
    return data.decode("utf-8", "replace").splitlines()


def mount_lines():
    wanted = {"/", RUNTIME_ROOT, SCRATCH}
    selected = []
    for line in read_lines("/proc/self/mountinfo"):
        fields = line.split(" ")
        if len(fields) > 5 and fields[4] in wanted:
            selected.append(line[:512])
    return selected


def scratch_names():
    try:
        return sorted(os.listdir(SCRATCH))
    except OSError:
        return None


def network_facts():
    names = sorted(name for _index, name in socket.if_nameindex())
    facts = []
    ipv6_lines = read_lines("/proc/net/if_inet6")
    ipv6_observed = os.path.isfile("/proc/net/if_inet6")
    for name in names[:4]:
        fact = {"name": name, "up": None, "ipv4": None, "ipv6": None, "observable": False}
        if not sys.platform.startswith("linux") or len(name.encode("ascii", "replace")) >= 16:
            facts.append(fact)
            continue
        try:
            request = struct.pack("256s", name.encode("ascii"))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                flags = fcntl.ioctl(sock.fileno(), 0x8913, request)
                fact["up"] = bool(struct.unpack_from("H", flags, 16)[0] & 1)
                try:
                    fcntl.ioctl(sock.fileno(), 0x8915, request)
                    fact["ipv4"] = True
                except OSError as error:
                    if error.errno != errno.EADDRNOTAVAIL:
                        raise
                    fact["ipv4"] = False
            fact["ipv6"] = any(line.split()[-1:] == [name] for line in ipv6_lines)
            fact["observable"] = ipv6_observed
        except (OSError, UnicodeError):
            pass
        facts.append(fact)
    return {"t": "ifaces", "names": names, "facts": facts}


def main():
    sink = Sink(sys.stdout.buffer)
    try:
        root_fd = os.open(RUNTIME_ROOT, DIR_FLAGS)
        try:
            sink.record(entry_header("", os.fstat(root_fd), "d"))
            count = 1 + walk(sink, root_fd, "")
        finally:
            os.close(root_fd)
        sink.record({"t": "mounts", "lines": mount_lines()})
        status = [line for line in read_lines("/proc/self/status") if line.startswith(STATUS_PREFIXES)]
        sink.record({"t": "status", "lines": status})
        sink.record({"t": "scratch", "names": scratch_names()})
        sink.record(network_facts())
        sink.record({"t": "end", "entries": count})
    except Refused as refusal:
        sys.stderr.write("readback_refused " + str(refusal) + "\n")
        return 4
    except OSError:
        sys.stderr.write("readback_refused os_error\n")
        return 4
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
