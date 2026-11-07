"""Negative containment probes, each run as the parser principal (spec 14.2).

The single argument selects one probe from a closed table. Refusal probes
print ``REFUSED <probe> <errno>`` and exit 0 when the operation was denied,
or ``ALLOWED <probe>`` and exit 1 when it unexpectedly succeeded. Resource
probes deliberately exceed one bound so the parent can observe its own
bound event. Standalone standard library only; never given target bytes.
"""

import errno
import os
import socket
import sys
import threading
import time
from collections.abc import Callable

RUNTIME_ROOT = "/opt/repomap-rust"
SCRATCH = "/scratch"
UNROUTABLE = ("192.0.2.1", 9)


def tcp():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.settimeout(2)
        handle.connect(UNROUTABLE)


def udp():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as handle:
        handle.sendto(b"probe", UNROUTABLE)


def create(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)


def write_root():
    create("/repomap-probe")


def write_prefix():
    create(RUNTIME_ROOT + "/probe")


def write_prefix_file():
    fd = os.open(RUNTIME_ROOT + "/helper/parse_helper.py", os.O_WRONLY | os.O_APPEND)
    os.close(fd)


def chmod_sealed():
    os.chmod(RUNTIME_ROOT + "/helper", 0o777)


def exec_scratch():
    path = SCRATCH + "/probe.sh"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    os.write(fd, b"#!/bin/sh\nexit 0\n")
    os.close(fd)
    pid = os.fork()
    if pid == 0:
        try:
            os.execv(path, [path])
        except OSError as error:
            os._exit(100 + (_errno_value(error) % 100))
    _pid, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    if code >= 100:
        raise OSError(code - 100, "exec refused")


def setuid_root():
    os.setuid(0)


def docker_socket():
    os.stat("/var/run/docker.sock")


def processes():
    threads: list[threading.Thread] = []
    try:
        while len(threads) < 40:
            thread = threading.Thread(target=time.sleep, args=(3,), daemon=True)
            thread.start()
            threads.append(thread)
    except RuntimeError:
        raise OSError(errno.EAGAIN, "thread limit") from None


REFUSAL_PROBES: dict[str, Callable[[], object]] = {
    "tcp": tcp, "udp": udp, "write_root": write_root, "write_prefix": write_prefix,
    "write_prefix_file": write_prefix_file, "chmod_sealed": chmod_sealed,
    "exec_scratch": exec_scratch, "setuid": setuid_root, "docker_socket": docker_socket,
    "processes": processes,
}


def memory():
    blocks: list[bytearray] = []
    while len(blocks) < 600:
        blocks.append(bytearray(1_048_576))
    sys.stdout.write("ALLOWED memory\n")
    return 1


def sleep():
    time.sleep(30)
    sys.stdout.write("ALLOWED sleep\n")
    return 1


def stdout_flood():
    chunk = b"x" * 65_536
    written = 0
    while written < 64 * 1_048_576:
        sys.stdout.buffer.write(chunk)
        written += len(chunk)
    sys.stdout.write("ALLOWED stdout_flood\n")
    return 1


def stderr_flood():
    chunk = b"y" * 4_096
    written = 0
    while written < 100 * 1_024:
        sys.stderr.buffer.write(chunk)
        written += len(chunk)
    sys.stderr.buffer.flush()
    return 0


def abort():
    os.abort()


RESOURCE_PROBES: dict[str, Callable[[], int]] = {
    "memory": memory, "sleep": sleep, "stdout_flood": stdout_flood,
    "stderr_flood": stderr_flood, "abort": abort,
}


def _errno_value(error: OSError) -> int:
    number = error.errno
    return number if number is not None else 0


def main():
    if len(sys.argv) != 2:
        return 2
    name = sys.argv[1]
    if name in RESOURCE_PROBES:
        return RESOURCE_PROBES[name]()
    probe = REFUSAL_PROBES.get(name)
    if probe is None:
        return 2
    try:
        probe()
    except OSError as error:
        sys.stdout.write("REFUSED " + name + " "
                         + errno.errorcode.get(_errno_value(error), "unknown") + "\n")
        return 0
    sys.stdout.write("ALLOWED " + name + "\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
