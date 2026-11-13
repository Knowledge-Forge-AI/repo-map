"""Explicitly owned cancellable traversal over the incumbent no-body probe."""
from __future__ import annotations
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from common_lore_index.graph._capture_control import CancelCheck, CaptureControl
from common_lore_index.graph._capture_discovery import CaptureDiscoveryHooks
from common_lore_index.graph.discovery_records import FileInfo


class ControlledCaptureDiscoveryHooks(CaptureDiscoveryHooks):
    def __init__(self, cancel_check: CancelCheck, stack: ExitStack) -> None:
        self.control = CaptureControl(cancel_check)
        self.stack = stack

    def walk(self, top: Path) -> Iterable[tuple[str, list[str], list[str]]]:
        return self.stack.enter_context(self.control.iterating(super().walk(top)))

    def content_hash(self, path: Path) -> str:
        self.control.check()
        return super().content_hash(path)

    def first_line(self, path: Path) -> str:
        self.control.check()
        return super().first_line(path)

    def is_go_generated_file(self, path: Path) -> bool:
        self.control.check()
        return super().is_go_generated_file(path)

    def completion(self, path: Path) -> bool:
        self.control.check()
        return super().completion(path)


def discover_controlled(discover: Callable[..., Any], root: Path,
                        exclude_paths: tuple[str, ...], control: CaptureControl) -> tuple[FileInfo, ...]:
    assert control.callback is not None
    with ExitStack() as stack:
        hooks = ControlledCaptureDiscoveryHooks(control.callback, stack)
        return control.collect(discover(root, exclude_paths=exclude_paths, io_hooks=hooks))


def discover_inventory(discover: Callable[..., Any], root: Path, exclude_paths: tuple[str, ...],
                       keywords: dict[str, Any], control: CaptureControl) -> tuple[FileInfo, ...]:
    if control.callback is not None and isinstance(keywords.get("io_hooks"), CaptureDiscoveryHooks):
        return discover_controlled(discover, root, exclude_paths, control)
    return control.collect(discover(root, exclude_paths=exclude_paths, **keywords))
